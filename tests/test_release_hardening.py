import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import database
from services.backup import create_verified_backup
from services.payment_automation import create_payment_order
from services.tenant_activation import activate_tenant


class ReleaseHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "hardening.db")
        self.db_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.db_patch.start()
        await database.init_db()
        self.tenant_a = await database.create_tenant(
            "Tenant A", "candidate-a", "admin-a", [101]
        )
        self.tenant_b = await database.create_tenant(
            "Tenant B", "candidate-b", "admin-b", [202]
        )

    async def asyncTearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    async def test_parallel_orders_never_share_exact_amount(self):
        first, second = await asyncio.gather(
            create_payment_order(self.tenant_a, 599_000, plan_code="growth"),
            create_payment_order(self.tenant_b, 599_000, plan_code="growth"),
        )
        self.assertNotEqual(first["amount"], second["amount"])

    async def test_expired_amount_stays_reserved_for_late_payment_window(self):
        first = await create_payment_order(self.tenant_a, 599_000, plan_code="growth")
        async with __import__("aiosqlite").connect(self.db_path) as db:
            await db.execute(
                "UPDATE payment_orders SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (first["id"],),
            )
            await db.commit()
        second = await create_payment_order(self.tenant_b, 599_000, plan_code="growth")
        self.assertNotEqual(first["amount"], second["amount"])

    async def test_failed_miniapp_provisioning_does_not_mark_pending_tenant_active(self):
        tenant = {
            "id": 77,
            "status": "pending",
            "bot_token": "candidate-token",
            "admin_bot_token": "admin-token",
            "admin_user_ids": [1],
            "bot_username": None,
        }
        update_status = AsyncMock()
        with (
            patch("services.tenant_activation.database.get_tenant", AsyncMock(return_value=tenant)),
            patch("webhook_app.register_new_tenant_webhook", AsyncMock(side_effect=["candidate_bot", "admin_bot"])),
            patch("webhook_app.configure_admin_miniapp", AsyncMock(side_effect=RuntimeError("boom"))),
            patch("services.tenant_activation.database.update_tenant_status", update_status),
        ):
            result = await activate_tenant(77)
        self.assertFalse(result["ok"])
        update_status.assert_not_awaited()

    async def test_backup_is_readable_restored_copy(self):
        backup = await asyncio.to_thread(create_verified_backup)
        self.assertIsNotNone(backup)
        self.assertTrue(Path(backup).exists())

    def test_webhook_source_never_uses_bot_token_in_route(self):
        source = Path("webhook_app.py").read_text(encoding="utf-8")
        self.assertNotIn("/webhook/{bot_token}", source)
        self.assertNotIn("TokenBasedRequestHandler", source)
        self.assertIn("secret_token=telegram_secret", source)
        self.assertIn("/telegram/{webhook_id}", source)


if __name__ == "__main__":
    unittest.main()
