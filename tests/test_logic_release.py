import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import aiosqlite
from aiohttp import web

from admin_bot import handlers_billing
from miniapp_api import candidate_decision
from services import database
from services.plans import get_plan


class LogicReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "logic.db")
        self.db_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.db_patch.start()
        await database.init_db()
        self.tenant_id = await database.create_tenant(
            "Logic Test", "candidate-token", "admin-token", [777]
        )

    async def asyncTearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    async def _save_app(self, key: str = "app") -> int:
        return await database.save_application(
            tenant_id=self.tenant_id,
            user_id=123,
            submission_key=key,
            username="user",
            full_name="Test Candidate",
            vacancy_key="sales",
            vacancy_title="Sales",
            answers={},
            ai_scores={},
            resume_file_id=None,
            video_file_id=None,
            status="pending",
        )

    async def test_new_trial_tenant_starts_with_clean_vacancy_workspace(self):
        active = await database.list_vacancies(self.tenant_id, active_only=True)
        self.assertEqual(active, [])
        usage = await database.get_subscription_usage(self.tenant_id)
        self.assertEqual(usage["vacancies_used"], 0)
        self.assertTrue(usage["vacancies_available"])

    async def test_vacancy_limit_cannot_be_bypassed_by_create_or_reactivate(self):
        await database.create_vacancy(
            tenant_id=self.tenant_id,
            key="one",
            title="One",
            reject_message="Rahmat, hozircha mos kelmadi.",
            questions=[{"key": "q1", "text": "Savol?"}],
            resume_required=False,
        )
        with self.assertRaises(database.VacancyLimitReached):
            await database.create_vacancy(
                tenant_id=self.tenant_id,
                key="two",
                title="Two",
                reject_message="Rahmat, hozircha mos kelmadi.",
                questions=[{"key": "q1", "text": "Savol?"}],
                resume_required=False,
            )
        self.assertTrue(await database.set_vacancy_active(self.tenant_id, "one", False))
        await database.create_vacancy(
            tenant_id=self.tenant_id,
            key="two",
            title="Two",
            reject_message="Rahmat, hozircha mos kelmadi.",
            questions=[{"key": "q1", "text": "Savol?"}],
            resume_required=False,
        )
        with self.assertRaises(database.VacancyLimitReached):
            await database.set_vacancy_active(self.tenant_id, "one", True)

    async def test_vacancy_reactivation_rejects_malformed_subscription_expiry(self):
        await database.create_vacancy(
            tenant_id=self.tenant_id,
            key="malformed-expiry",
            title="Malformed expiry",
            reject_message="Rahmat, hozircha mos kelmadi.",
            questions=[{"key": "q1", "text": "Savol?"}],
            resume_required=False,
        )
        self.assertTrue(
            await database.set_vacancy_active(self.tenant_id, "malformed-expiry", False)
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE tenants SET plan_code='start', subscription_expires_at=? WHERE id=?",
                ("not-a-date", self.tenant_id),
            )
            await db.commit()
        with self.assertRaises(database.VacancyLimitReached):
            await database.set_vacancy_active(self.tenant_id, "malformed-expiry", True)

    async def test_duplicate_slot_and_booked_slot_delete_are_blocked(self):
        slot_id = await database.add_interview_slot(
            self.tenant_id, "2026-09-05 10:00", capacity=1
        )
        with self.assertRaises(database.InterviewSlotConflict):
            await database.add_interview_slot(
                self.tenant_id, "2026-09-05 10:00", capacity=2
            )
        app_id = await self._save_app("slot-app")
        self.assertTrue(
            await database.try_book_slot(
                self.tenant_id, app_id, "2026-09-05 10:00", 1
            )
        )
        with self.assertRaises(database.InterviewSlotBooked):
            await database.delete_interview_slot(self.tenant_id, slot_id)

    async def test_parallel_slot_booking_never_overbooks_and_duplicate_is_idempotent(self):
        slot_id = await database.add_interview_slot(
            self.tenant_id, "2026-09-05 11:00", capacity=1
        )
        first_app = await self._save_app("parallel-slot-1")
        second_app = await self._save_app("parallel-slot-2")

        results = await asyncio.gather(
            database.book_interview_slot(self.tenant_id, first_app, slot_id),
            database.book_interview_slot(self.tenant_id, second_app, slot_id),
        )
        self.assertCountEqual(results, ["booked", "full"])
        self.assertEqual(
            await database.count_slot_bookings(self.tenant_id, "2026-09-05 11:00"),
            1,
        )

        booked_app = first_app if results[0] == "booked" else second_app
        self.assertEqual(
            await database.book_interview_slot(self.tenant_id, booked_app, slot_id),
            "already_booked",
        )

    async def test_slot_booking_rechecks_active_slot_inside_transaction(self):
        slot_id = await database.add_interview_slot(
            self.tenant_id, "2026-09-05 12:00", capacity=1
        )
        app_id = await self._save_app("deleted-slot")
        self.assertTrue(await database.delete_interview_slot(self.tenant_id, slot_id))

        self.assertEqual(
            await database.book_interview_slot(self.tenant_id, app_id, slot_id),
            "unavailable",
        )
        app = await database.get_application(self.tenant_id, app_id)
        self.assertIsNone(app["selected_slot"])

    async def test_expired_payment_order_is_expired_on_read_and_not_reminded(self):
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO payment_orders "
                "(tenant_id, order_code, base_amount, amount, plan_code, billing_months, "
                "status, created_at, expires_at) VALUES (?, ?, ?, ?, 'start', 1, "
                "'awaiting_payment', ?, ?)",
                (
                    self.tenant_id,
                    "JH-OLD",
                    299000,
                    299006,
                    (now - timedelta(hours=1)).isoformat(),
                    (now - timedelta(minutes=30)).isoformat(),
                ),
            )
            await db.commit()
        order = await database.get_payment_order_for_tenant(self.tenant_id, "JH-OLD")
        self.assertEqual(order["status"], "expired")
        self.assertEqual(await database.list_unpaid_orders_older_than(minutes=30), [])

    async def test_admin_bot_blocks_active_plan_downgrade_before_order_creation(self):
        callback = type(
            "Callback",
            (),
            {
                "data": "billing:buy:start",
                "answer": AsyncMock(),
                "message": type("Message", (), {"edit_text": AsyncMock()})(),
            },
        )()
        usage = {
            "plan": get_plan("business"),
            "expired": False,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        }
        with (
            patch.object(handlers_billing, "PAYMENT_CARD_NUMBER", "8600"),
            patch.object(database, "get_subscription_usage", AsyncMock(return_value=usage)),
            patch.object(handlers_billing, "create_payment_order", AsyncMock()) as create_order,
        ):
            await handlers_billing.billing_buy(callback, self.tenant_id)
        create_order.assert_not_awaited()
        self.assertTrue(callback.answer.await_args.kwargs["show_alert"])

    async def test_miniapp_cannot_accept_candidate_without_interview_slot(self):
        request = type(
            "Request",
            (),
            {
                "match_info": {"app_id": "9"},
                "json": AsyncMock(return_value={"action": "accept"}),
            },
        )()
        app = {"id": 9, "status": "pending", "user_id": 123, "lang": "uz"}
        tenant = {"id": self.tenant_id, "bot_token": "token"}
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=(tenant, {}))),
            patch.object(database, "get_application", AsyncMock(return_value=app)),
            patch.object(database, "get_available_interview_slots", AsyncMock(return_value=[])),
            patch.object(database, "transition_application_status", AsyncMock()) as transition,
            self.assertRaises(web.HTTPConflict),
        ):
            await candidate_decision(request)
        transition.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
