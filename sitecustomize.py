"""Optional, temporary payout-flow test harness.

Normal production behavior is unchanged unless the dedicated Render test
environment variables are set. The test path never writes a fake sale or payout
to the real commission ledger and Founder Bot is told not to transfer money.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone


_TEST_CODE = (os.getenv("PARTNER_PAYOUT_TEST_REFERRAL_CODE") or "").strip().upper()
try:
    _TEST_AMOUNT = max(0, int(os.getenv("PARTNER_PAYOUT_TEST_BALANCE_AMOUNT") or "0"))
except (TypeError, ValueError):
    _TEST_AMOUNT = 0
_TEST_EXPIRES = (os.getenv("PARTNER_PAYOUT_TEST_EXPIRES_AT_UTC") or "").strip()
_TEST_STATE: dict[int, dict] = {}


def _test_enabled() -> bool:
    if not _TEST_CODE or _TEST_AMOUNT <= 0:
        return False
    if not _TEST_EXPIRES:
        return True
    try:
        expires = datetime.fromisoformat(_TEST_EXPIRES.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < expires
    except ValueError:
        return False


def _install_test_patch() -> None:
    if not _test_enabled():
        return

    # Wait until the application dependencies are importable. This thread is
    # daemon-only, so it does not slow or block normal startup/build commands.
    for _ in range(30):
        if not _test_enabled():
            return
        try:
            from aiogram.client.default import DefaultBotProperties
            from aiogram.enums import ParseMode
            import partner_payout_bot as payout_bot
            from services import partner_database as pdb
            from services import partner_payouts as payouts
            break
        except Exception:
            time.sleep(1)
    else:
        return

    if getattr(payouts, "_temporary_safe_test_mode_installed", False):
        return
    payouts._temporary_safe_test_mode_installed = True

    real_get_balance = payouts.get_partner_balance
    real_create_request = payouts.create_payout_request
    real_notify_founders = payout_bot._notify_founders_about_payout

    async def _test_partner(partner_id: int) -> dict | None:
        if not _test_enabled():
            return None
        partner = await pdb.get_partner(int(partner_id))
        if not partner:
            return None
        code = str(partner.get("referral_code") or "").strip().upper()
        if code != _TEST_CODE:
            return None
        return partner

    async def test_get_partner_balance(partner_id: int) -> dict:
        real = await real_get_balance(partner_id)
        partner = await _test_partner(partner_id)
        if not partner:
            return real

        # Never mix a synthetic test amount with genuine withdrawable money.
        # If a real commission appears, the real ledger wins automatically.
        if int(real.get("available") or 0) > 0 or int(real.get("earned") or 0) > 0:
            return real

        active = _TEST_STATE.get(int(partner_id))
        if active:
            return {
                **real,
                "sale_count": 1,
                "earned": _TEST_AMOUNT,
                "reserved": _TEST_AMOUNT,
                "paid": 0,
                "available": 0,
                "active_request": active,
                "test_mode": True,
            }
        return {
            **real,
            "sale_count": 1,
            "earned": _TEST_AMOUNT,
            "reserved": 0,
            "paid": 0,
            "available": _TEST_AMOUNT,
            "active_request": None,
            "test_mode": True,
        }

    async def test_create_payout_request(
        partner_id: int,
        full_name: str,
        card_number: str | None = None,
        receipt_username: str | None = None,
        *,
        payment_details: str | None = None,
    ) -> dict:
        partner = await _test_partner(partner_id)
        real = await real_get_balance(partner_id)
        if not partner or int(real.get("available") or 0) > 0 or int(real.get("earned") or 0) > 0:
            return await real_create_request(
                partner_id,
                full_name,
                card_number,
                receipt_username,
                payment_details=payment_details,
            )

        existing = _TEST_STATE.get(int(partner_id))
        if existing:
            return {"ok": False, "error": "Test pul yechish arizasi hali yopilmagan."}

        if card_number is None and receipt_username is None:
            return {"ok": False, "error": "Test Mini App orqali yuborilsin."}

        clean_name, clean_card, clean_username, error = payouts.validate_payout_details(
            full_name, card_number or "", receipt_username or ""
        )
        if error:
            return {"ok": False, "error": error}

        now = datetime.now(timezone.utc).isoformat()
        request_id = 900000000 + int(partner_id)
        request = {
            "ok": True,
            "id": request_id,
            "partner_id": int(partner_id),
            "partner_name": partner.get("full_name") or "Hamkor",
            "partner_username": partner.get("username") or "",
            "partner_phone": partner.get("phone") or "",
            "partner_telegram_user_id": partner.get("telegram_user_id"),
            "requested_amount": _TEST_AMOUNT,
            "bonus_amount": 0,
            "total_amount": _TEST_AMOUNT,
            "payment_details": "TEST MODE",
            "status": "pending",
            "payout_due_date": payouts.next_payout_date().isoformat(),
            "requested_at": now,
            "payout_full_name": clean_name,
            "payout_card_number": clean_card,
            "receipt_telegram_username": clean_username,
            "delay_days": 0,
            "note": "TEST_MODE_NO_REAL_PAYOUT",
            "test_mode": True,
            "items": [
                {
                    "tenant_id": None,
                    "company_name": "TEST MIJOZ",
                    "plan_code": "start",
                    "sale_amount": 299000,
                    "commission_amount": _TEST_AMOUNT,
                    "metadata": '{"test_mode": true}',
                }
            ],
        }
        _TEST_STATE[int(partner_id)] = request
        return request

    async def test_notify_founders(source_bot, request: dict, *, title: str) -> bool:
        if not request.get("test_mode"):
            return await real_notify_founders(source_bot, request, title=title)
        if not payout_bot.FOUNDER_BOT_TOKEN or not payout_bot.FOUNDER_USER_IDS:
            return False

        founder_bot = payout_bot.Bot(
            token=payout_bot.FOUNDER_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        sent_any = False
        text = (
            f"🧪 <b>TEST — Hamkor pul yechish arizasi #{request['id']}</b>\n\n"
            f"Hamkor: <b>{request.get('partner_name') or 'Hamkor'}</b>\n"
            f"Partner ID: <code>{request['partner_id']}</code>\n\n"
            f"👤 Ism-familiya: <b>{request.get('payout_full_name') or '—'}</b>\n"
            f"💳 Karta raqami: <code>{request.get('payout_card_number') or '—'}</code>\n"
            f"🧾 Chek username: <b>{request.get('receipt_telegram_username') or '—'}</b>\n\n"
            f"Test balans: <b>{pdb.format_uzs(request.get('requested_amount') or 0)}</b>\n"
            f"Test o'tkazma: <b>{pdb.format_uzs(request.get('total_amount') or 0)}</b>\n"
            f"To'lov muddati: <b>{request.get('payout_due_date') or '—'}</b>\n\n"
            "⚠️ <b>BU TEST.</b> Real savdo yaratilmagan, real komissiya o'zgarmagan va "
            "bu ariza bo'yicha REAL PUL YUBORMANG."
        )
        try:
            for founder_id in payout_bot.FOUNDER_USER_IDS:
                try:
                    await founder_bot.send_message(founder_id, text)
                    sent_any = True
                except Exception:
                    pass
        finally:
            await founder_bot.session.close()
        return sent_any

    payouts.get_partner_balance = test_get_partner_balance
    payouts.create_payout_request = test_create_payout_request
    payout_bot._notify_founders_about_payout = test_notify_founders


if _test_enabled():
    threading.Thread(target=_install_test_patch, name="partner-payout-test", daemon=True).start()
