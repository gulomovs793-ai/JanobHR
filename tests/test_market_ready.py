import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from admin_bot.handlers_menu import ADMIN_MENU, _main_menu_keyboard, _service_keyboard
from services import database


class MarketReadyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "market.db")
        self.path_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.path_patch.start()
        await database.init_db()
        self.tenant_id = await database.create_tenant(
            "Market Test", "candidate-token", "admin-token", [777]
        )

    async def asyncTearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    async def _save(self, key: str, *, user_id: int = 1) -> int:
        return await database.save_application(
            tenant_id=self.tenant_id,
            user_id=user_id,
            submission_key=key,
            username="test",
            full_name="Test User",
            vacancy_key="sales",
            vacancy_title="Sales",
            answers={},
            ai_scores={},
            resume_file_id=None,
            video_file_id=None,
            status="pending",
        )

    async def test_admin_chat_menu_has_no_management_panel_button(self):
        markup = _service_keyboard(self.tenant_id)
        labels = [button.text for row in markup.keyboard for button in row]
        self.assertNotIn("panel", ADMIN_MENU)
        self.assertNotIn("🖥 Boshqaruv paneli", labels)

    async def test_admin_inline_menu_has_no_management_panel_button(self):
        markup = _main_menu_keyboard({"pending": 2}, self.tenant_id)
        buttons = [button for row in markup.inline_keyboard for button in row]
        self.assertNotIn("🖥 Boshqaruv paneli", [button.text for button in buttons])
        self.assertTrue(all(button.web_app is None for button in buttons))

    def test_admin_panel_remains_on_telegram_side_menu(self):
        source = Path("webhook_app.py").read_text(encoding="utf-8")
        self.assertIn('text="Boshqaruv paneli"', source)
        self.assertIn("set_chat_menu_button", source)
        self.assertIn("MenuButtonWebApp", source)

    async def test_submission_key_is_idempotent(self):
        first = await self._save("same-key", user_id=10)
        second = await self._save("same-key", user_id=10)
        self.assertEqual(first, second)
        _, total = await database.list_applications(self.tenant_id, limit=20)
        self.assertEqual(total, 1)

    async def test_trial_limit_is_enforced_inside_save_transaction(self):
        for index in range(5):
            await self._save(f"key-{index}", user_id=100 + index)
        with self.assertRaises(database.ApplicationLimitReached):
            await self._save("sixth", user_id=999)
        _, total = await database.list_applications(self.tenant_id, limit=20)
        self.assertEqual(total, 5)

    async def test_only_one_competing_admin_decision_wins(self):
        app_id = await self._save("decision-key")
        accepted = await database.transition_application_status(
            self.tenant_id, app_id, "accepted", {"pending", "saved"}
        )
        declined = await database.transition_application_status(
            self.tenant_id, app_id, "declined", {"pending", "saved"}
        )
        self.assertTrue(accepted)
        self.assertFalse(declined)
        app = await database.get_application(self.tenant_id, app_id)
        self.assertEqual(app["status"], "accepted")

    async def test_auto_slot_booking_moves_pending_candidate_to_accepted(self):
        app_id = await self._save("slot-key")
        booked = await database.try_book_slot(
            self.tenant_id, app_id, "2026-09-05 10:00", 1
        )
        repeated = await database.try_book_slot(
            self.tenant_id, app_id, "2026-09-05 10:00", 1
        )
        self.assertTrue(booked)
        self.assertTrue(repeated)
        app = await database.get_application(self.tenant_id, app_id)
        self.assertEqual(app["status"], "accepted")
        self.assertEqual(app["selected_slot"], "2026-09-05 10:00")

    async def test_database_healthcheck_is_real(self):
        self.assertTrue(await database.healthcheck())

    def test_webhook_startup_does_not_drop_pending_updates(self):
        source = Path("webhook_app.py").read_text(encoding="utf-8")
        self.assertIn("drop_pending_updates=False", source)
        self.assertNotIn("drop_pending_updates=True", source)


if __name__ == "__main__":
    unittest.main()
