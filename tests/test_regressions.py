import tempfile
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import AsyncMock, patch

from aiogram.fsm.storage.base import StorageKey

import webhook_app
from handlers import admin as admin_handlers
from services import database
from services.payment_automation import handle_payment_notification
from services.storage import SQLiteStorage


class FakeAdminBot:
    created_tokens: ClassVar[list[str]] = []

    def __init__(self, token):
        self.created_tokens.append(token)
        self.send_message = AsyncMock(
            return_value=type("Sent", (), {"message_id": 99})()
        )
        self.send_document = AsyncMock()
        self.send_video = AsyncMock()
        self.send_voice = AsyncMock()
        self.session = type("Session", (), {"close": AsyncMock()})()


class RegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fsm_storage_initializes_on_fresh_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = SQLiteStorage(str(Path(tmp) / "fsm.db"))
            await storage.init()
            key = StorageKey(bot_id=1, chat_id=2, user_id=3)
            await storage.set_state(key, "apply:name")
            await storage.set_data(key, {"tenant_id": 7})
            self.assertEqual(await storage.get_state(key), "apply:name")
            self.assertEqual(await storage.get_data(key), {"tenant_id": 7})

    async def test_failed_activation_is_not_reported_as_approved(self):
        order = {"id": 10, "tenant_id": 20, "order_code": "JH-TEST"}
        notify = AsyncMock()
        activate = AsyncMock(return_value={"ok": False, "error": "webhook failed"})

        with (
            patch.object(
                database,
                "was_notification_seen_recently",
                AsyncMock(return_value=False),
            ),
            patch.object(database, "record_seen_notification", AsyncMock()),
            patch.object(
                database,
                "get_open_payment_orders_by_amount",
                AsyncMock(return_value=[order]),
            ),
            patch.object(
                database, "try_approve_payment_order", AsyncMock(return_value=True)
            ),
            patch.object(
                database, "mark_payment_order_needs_review", AsyncMock()
            ) as mark_review,
        ):
            result = await handle_payment_notification(
                "+ 500 001 so'm", notify, activate
            )

        self.assertNotEqual(result["status"], "approved")
        mark_review.assert_awaited_once()
        self.assertIn("xatosi", notify.await_args.args[0])

    async def test_application_is_sent_by_admin_bot(self):
        tenant = {
            "admin_user_ids": [123],
            "admin_bot_token": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi",
        }
        app = {
            "tenant_id": 1,
            "user_id": 456,
            "full_name": "Test Candidate",
            "vacancy_title": "Sales",
            "vacancy_key": "sales",
            "answers": {},
            "ai_scores": {},
            "voice_answers": {},
            "resume_file_id": None,
            "video_file_id": None,
            "username": "test",
            "phone_number": "+998",
            "ai_suspect_flags": [],
            "selected_slot": None,
        }
        candidate_bot = type("CandidateBot", (), {})()
        FakeAdminBot.created_tokens.clear()

        with (
            patch.object(database, "get_tenant", AsyncMock(return_value=tenant)),
            patch.object(database, "get_application", AsyncMock(return_value=app)),
            patch.object(database, "get_vacancy", AsyncMock(return_value=None)),
            patch.object(database, "add_admin_message", AsyncMock()) as add_message,
            patch.object(admin_handlers, "Bot", FakeAdminBot),
        ):
            await admin_handlers.notify_admins(1, 2, candidate_bot)

        self.assertEqual(FakeAdminBot.created_tokens, [tenant["admin_bot_token"]])
        add_message.assert_awaited_once_with(1, 2, 123, 99)

    async def test_webhook_requires_public_base_url(self):
        with (
            patch.object(webhook_app, "WEBHOOK_BASE_URL", ""),
            self.assertRaisesRegex(RuntimeError, "WEBHOOK_BASE_URL"),
        ):
            await webhook_app.register_new_tenant_webhook("invalid-token")


if __name__ == "__main__":
    unittest.main()
