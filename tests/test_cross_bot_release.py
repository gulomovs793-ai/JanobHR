"""Release contracts across referral, billing, candidate and founder surfaces."""
import asyncio
import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

import aiosqlite
from aiogram.fsm.storage.base import StorageKey
from aiohttp import web

import config
import founder_miniapp_api
import miniapp_api
import partner_miniapp_api
from handlers import admin
from services import database, partner_payouts, tenant_middleware
from services import partner_database as pdb
from services.payment_automation import (
    create_payment_order,
    handle_payment_notification,
)
from services.storage import SQLiteStorage
from userbot import _notify_tenant_payment_approved


def token(bot_id):
    return f'{bot_id}:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi'


def signed(user, bot_token):
    values = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': user})}
    check = '\n'.join(f'{k}={values[k]}' for k in sorted(values))
    key = hmac.new(b'WebAppData', bot_token.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class CrossBotReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / 'release.db')
        for module in (database, pdb, partner_payouts):
            self.enterContext(patch.object(module, 'SQLITE_PATH', self.db_path))
        await database.init_db()
        await pdb.init_partner_db()
        await partner_payouts.init_partner_payout_db()
        self.tenant = await database.create_tenant('Acme', token(10001), token(10002), [101])
        self.other = await database.create_tenant('Other', token(20001), token(20002), [202])
        await database.update_tenant_status(self.tenant, 'active')
        await database.update_tenant_status(self.other, 'active')

    async def partner(self, uid):
        p = await pdb.upsert_application(user_id=uid, full_name=f'Partner {uid}', username='',
                                         phone=f'+99890000{uid:04}', role='agency',
                                         has_business_clients=True, client_band='1-3')
        return await pdb.set_partner_status(p['id'], 'approved', expected_status='pending')

    async def lead(self, partner=None):
        return await database.save_business_lead(telegram_user_id=101, contact_phone='+998901234567',
                                                 company_name='Acme', partner_id=(partner or {}).get('id'),
                                                 partner_referral_code=(partner or {}).get('referral_code'))

    async def pay(self, order):
        notice = AsyncMock()
        with patch('services.payment_automation.card_matches_ours', return_value=True):
            result = await handle_payment_notification(f"🟢 Perevod na kartu\n➕ {order['amount']}.00 UZS",
                                                       notice, AsyncMock(return_value={'ok': True}))
        return result, notice

    async def test_referral_to_payment_candidate_and_founder_end_to_end(self):
        partner = await self.partner(303)
        self.assertTrue(await pdb.record_referral_click(partner['id'], 101))
        self.assertFalse(await pdb.record_referral_click(partner['id'], 101))
        lead_id = await self.lead(partner)
        await database.attach_business_lead_to_tenant(lead_id, self.tenant)
        self.assertTrue(await pdb.record_referral_trial(partner['id'], 101, self.tenant))
        self.assertFalse(await pdb.record_referral_trial(partner['id'], 101, self.tenant))
        attr = await pdb.prepare_payment_attribution(self.tenant, 'start')
        order = await create_payment_order(self.tenant, attr['discounted_base_amount'], plan_code='start', attribution=attr)
        self.assertEqual((await database.get_business_lead(lead_id))['status'], 'payment')
        result, _ = await self.pay(order)
        self.assertEqual(result['status'], 'approved')
        activated = await database.get_tenant(self.tenant)
        self.assertEqual(activated['plan_code'], 'start')
        retry = await database.activate_subscription_for_order(order['id'])
        self.assertTrue(retry['already_activated'])
        self.assertEqual((await database.get_tenant(self.tenant))['subscription_expires_at'], activated['subscription_expires_at'])
        await pdb.finalize_sale_for_order(order['id'], actual_amount=order['amount'])
        self.assertEqual((await pdb.get_partner_stats(partner['id']))['sales'], 1)
        self.assertEqual((await partner_payouts.get_partner_balance(partner['id']))['earned'], attr['commission_amount'])
        self.assertEqual((await pdb.get_partner_leads(partner['id']))[0]['status'], 'customer')
        app_id = await database.save_application(tenant_id=self.tenant, user_id=404, username='',
                    full_name='Nomzod', vacancy_key='sales', vacancy_title='Sales', answers={'q': 'Answer'},
                    ai_scores={}, resume_file_id=None, video_file_id=None, status='pending', submission_key='unique')
        self.assertIsNone(await database.get_application(self.other, app_id))
        self.assertFalse(await database.transition_application_status(self.other, app_id, 'declined', {'pending'}))
        self.assertTrue(await database.transition_application_status(self.tenant, app_id, 'accepted', {'pending'}))
        self.assertEqual((await database.get_latest_application_for_user(self.tenant, 404))['status'], 'accepted')
        self.assertEqual((await database.get_founder_dashboard_data())['revenue']['all'], order['amount'])

    async def test_direct_sale_updates_founder_without_false_partner_warning(self):
        lead_id = await self.lead()
        await database.attach_business_lead_to_tenant(lead_id, self.tenant)
        order = await create_payment_order(self.tenant, 299000, plan_code='start')
        self.assertEqual((await database.get_business_lead(lead_id))['status'], 'payment')
        result, notices = await self.pay(order)
        self.assertEqual(result['status'], 'approved')
        self.assertEqual((await database.get_business_lead(lead_id))['status'], 'customer')
        self.assertNotIn('komissiya', ' '.join(str(c) for c in notices.await_args_list))

    async def test_reentry_preserves_first_partner_and_lead_visibility(self):
        first, second = await self.partner(301), await self.partner(302)
        lead_id = await self.lead(first)
        await self.lead(second)
        self.assertEqual((await database.get_business_lead(lead_id))['partner_id'], first['id'])
        await database.attach_business_lead_to_tenant(lead_id, self.tenant)
        await pdb.record_referral_trial(first['id'], 101, self.tenant)
        # Legacy inconsistent rows must still obey the canonical tenant attribution.
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('UPDATE business_leads SET partner_id=? WHERE id=?', (second['id'], lead_id))
            await db.commit()
        self.assertEqual(len(await pdb.get_partner_leads(first['id'])), 1)
        self.assertEqual(await pdb.get_partner_leads(second['id']), [])

    async def test_first_referral_click_cannot_be_replaced_before_lead_exists(self):
        first, second = await self.partner(301), await self.partner(302)
        self.assertTrue(await pdb.record_referral_click(first['id'], 101))
        self.assertFalse(await pdb.record_referral_click(second['id'], 101))
        canonical = await pdb.get_first_referral_partner_for_user(101)
        self.assertEqual(canonical['id'], first['id'])
        self.assertEqual((await pdb.get_partner_stats(first['id']))['clicks'], 1)
        self.assertEqual((await pdb.get_partner_stats(second['id']))['clicks'], 0)

    async def test_trial_cannot_credit_second_partner_after_promo_claim(self):
        first, second = await self.partner(301), await self.partner(302)
        await pdb.claim_tenant_attribution(self.tenant, first['id'], source='promo_code')
        self.assertFalse(await pdb.record_referral_trial(second['id'], 101, self.tenant))
        self.assertEqual((await pdb.get_partner_stats(second['id']))['trials'], 0)

    async def test_concurrent_cross_role_token_registration_has_one_winner(self):
        outcomes = await asyncio.gather(
            database.create_tenant('A', token(30001), token(30002), [1]),
            database.create_tenant('B', token(30002), token(30003), [2]), return_exceptions=True)
        self.assertEqual(sum(isinstance(value, int) for value in outcomes), 1)
        self.assertEqual(sum(isinstance(value, ValueError) for value in outcomes), 1)

    async def test_platform_and_rotated_bot_tokens_cannot_be_reused(self):
        with patch.object(config, 'FOUNDER_BOT_TOKEN', token(99999)), self.assertRaises(ValueError):
            await database.create_tenant('Wrong', token(99999) + 'rotated', token(50000), [1])
        with self.assertRaises(ValueError):
            await database.create_tenant('Wrong', token(10002) + 'rotated', token(50000), [1])
        with self.assertRaises(ValueError):
            await database.create_tenant('Wrong', token(50000), token(50000) + 'rotated', [1])

    async def test_receipt_waits_for_actual_activation_and_uses_admin_bot(self):
        order = await create_payment_order(self.tenant, 299000, plan_code='start')
        await database.try_approve_payment_order(order['id'])
        self.assertEqual(await database.list_unnotified_approved_orders(), [])
        with patch('aiogram.Bot') as factory:
            self.assertFalse(await _notify_tenant_payment_approved({**order, 'tenant_id': self.tenant}))
            factory.assert_not_called()
        await database.activate_subscription_for_order(order['id'])
        fake = SimpleNamespace(send_message=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
        with patch('aiogram.Bot', return_value=fake) as factory:
            self.assertTrue(await _notify_tenant_payment_approved({**order, 'tenant_id': self.tenant}))
            factory.assert_called_once_with(token=token(10002))
        self.assertEqual(await database.list_unnotified_approved_orders(), [])
        fake.send_message.assert_awaited_once()
        self.assertNotIn('commission', str(fake.send_message.call_args))

    async def test_expired_receipt_failure_remains_retryable_after_one_day(self):
        order = await create_payment_order(self.tenant, 299000, plan_code='start')
        await database.try_approve_payment_order(order['id'])
        await database.activate_subscription_for_order(order['id'])
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE payment_orders SET decided_at='2020-01-01T00:00:00+00:00' WHERE id=?", (order['id'],))
            await db.commit()
        self.assertEqual(len(await database.list_unnotified_approved_orders()), 1)

    async def test_parallel_receipt_recovery_sends_once_per_admin(self):
        order = await create_payment_order(self.tenant, 299000, plan_code='start')
        await database.try_approve_payment_order(order['id'])
        await database.activate_subscription_for_order(order['id'])
        fake = SimpleNamespace(send_message=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))
        payload = {**order, 'tenant_id': self.tenant}
        with patch('aiogram.Bot', return_value=fake):
            results = await asyncio.gather(
                _notify_tenant_payment_approved(payload),
                _notify_tenant_payment_approved(payload),
            )
        self.assertEqual(fake.send_message.await_count, 1)
        self.assertIn(True, results)
        self.assertEqual(await database.list_unnotified_approved_orders(), [])

    async def test_failed_admin_receipt_retries_only_that_admin(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE tenants SET admin_user_ids=? WHERE id=?",
                (json.dumps([101, 202]), self.tenant),
            )
            await db.commit()
        order = await create_payment_order(self.tenant, 299000, plan_code='start')
        await database.try_approve_payment_order(order['id'])
        await database.activate_subscription_for_order(order['id'])

        async def fail_second(admin_id, _text):
            if admin_id == 202:
                raise RuntimeError('temporary Telegram failure')

        first_bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=fail_second),
            session=SimpleNamespace(close=AsyncMock()),
        )
        payload = {**order, 'tenant_id': self.tenant}
        with patch('aiogram.Bot', return_value=first_bot):
            self.assertFalse(await _notify_tenant_payment_approved(payload))
        self.assertEqual(len(await database.list_unnotified_approved_orders()), 1)

        retry_bot = SimpleNamespace(
            send_message=AsyncMock(), session=SimpleNamespace(close=AsyncMock())
        )
        with patch('aiogram.Bot', return_value=retry_bot):
            self.assertTrue(await _notify_tenant_payment_approved(payload))
        retry_bot.send_message.assert_awaited_once()
        self.assertEqual(retry_bot.send_message.await_args.args[0], 202)
        self.assertEqual(await database.list_unnotified_approved_orders(), [])

    async def test_failed_resume_download_does_not_hide_admin_card(self):
        app_id = await database.save_application(tenant_id=self.tenant, user_id=404, username='',
            full_name='Nomzod', vacancy_key='sales', vacancy_title='Sales', answers={}, ai_scores={},
            resume_file_id='expired-file', video_file_id=None, status='pending')
        fake = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=9)), send_document=AsyncMock(),
                               session=SimpleNamespace(close=AsyncMock()))
        with patch('handlers.admin.Bot', return_value=fake):
            await admin.notify_admins(self.tenant, app_id, SimpleNamespace(download=AsyncMock(side_effect=RuntimeError('expired'))))
        fake.send_message.assert_awaited_once()
        self.assertEqual(len((await database.get_application(self.tenant, app_id))['admin_messages']), 1)

    async def test_api_auth_isolated_for_founder_partner_and_tenant(self):
        p = await self.partner(303)
        req = lambda user, key: SimpleNamespace(headers={'X-Telegram-Init-Data': signed(user, key)}, match_info={'tenant_id': str(self.tenant)}, query={})
        with patch.object(founder_miniapp_api, 'FOUNDER_BOT_TOKEN', token(90001)), patch.object(founder_miniapp_api, 'FOUNDER_USER_IDS', {999}):
            with self.assertRaises(web.HTTPUnauthorized):
                founder_miniapp_api._authorize_founder(req(999, token(10002)))
            with self.assertRaises(web.HTTPForbidden):
                founder_miniapp_api._authorize_founder(req(101, token(90001)))
        with patch.object(partner_miniapp_api, 'PARTNER_BOT_TOKEN', token(90002)):
            approved, error = await partner_miniapp_api._approved_partner(req(303, token(90002)))
            self.assertEqual(approved['id'], p['id'])
            approved, error = await partner_miniapp_api._approved_partner(req(303, token(10002)))
            self.assertEqual(error.status, 401)
        with self.assertRaises(web.HTTPForbidden):
            await miniapp_api._authorize(req(202, token(10002)))
        with self.assertRaises(web.HTTPUnauthorized):
            await miniapp_api._authorize(req(101, token(20002)))

    async def test_tenant_roles_and_sessions_do_not_bleed_between_bots(self):
        middleware = tenant_middleware.TenantMiddleware()
        for bot_id, expected_role, expected_admin in [(10001, 'candidate', False), (10002, 'admin', True), (20002, 'admin', False)]:
            data = {'bot': SimpleNamespace(token=token(bot_id)), 'event_from_user': SimpleNamespace(id=101)}
            handler = AsyncMock()
            await middleware(handler, SimpleNamespace(), data)
            self.assertEqual(data['bot_role'], expected_role)
            self.assertEqual(data['is_admin'], expected_admin)
        storage = SQLiteStorage(self.db_path)
        await storage.init()
        candidate, partner = StorageKey(bot_id=10001, chat_id=101, user_id=101), StorageKey(bot_id=90002, chat_id=101, user_id=101)
        await storage.set_data(candidate, {'answer': 'private'})
        self.assertEqual(await storage.get_data(partner), {})
