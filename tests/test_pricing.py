import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from services import database
from services.payment_automation import handle_payment_notification


class PricingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "pricing.db")
        self.path_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.path_patch.start()
        await database.init_db()
        self.tenant_id = await database.create_tenant(
            "Test", "candidate-token", "admin-token", [1]
        )

    async def asyncTearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    async def test_new_tenant_starts_with_five_free_applications(self):
        usage = await database.get_subscription_usage(self.tenant_id)
        self.assertEqual(usage["plan"].code, "trial")
        self.assertEqual(usage["plan"].application_limit, 5)
        self.assertTrue(usage["applications_available"])

    async def test_paid_plan_is_saved_on_payment_order(self):
        order_id = await database.create_payment_order(
            self.tenant_id,
            "JH-PLAN",
            599_000,
            599_101,
            "2099-01-01T00:00:00+00:00",
            plan_code="growth",
        )
        orders = await database.get_open_payment_orders_by_amount(599_101)
        self.assertEqual(orders[0]["id"], order_id)
        self.assertEqual(orders[0]["plan_code"], "growth")

    async def test_payment_activates_selected_subscription(self):
        await database.create_payment_order(
            self.tenant_id,
            "JH-PAID",
            299_000,
            299_111,
            "2099-01-01T00:00:00+00:00",
            plan_code="start",
        )
        notify = AsyncMock()
        activate = AsyncMock(return_value={"ok": True})
        with (
            patch("services.payment_automation.PAYMENT_CARD_NUMBER", "8600123412341234"),
            patch.object(database, "was_notification_seen_recently", AsyncMock(return_value=False)),
            patch.object(database, "record_seen_notification", AsyncMock()),
        ):
            result = await handle_payment_notification(
                "+ 299 111 so'm karta **1234", notify, activate
            )
        self.assertEqual(result["status"], "approved")
        tenant = await database.get_tenant(self.tenant_id)
        self.assertEqual(tenant["plan_code"], "start")
        self.assertIsNotNone(tenant["subscription_expires_at"])


if __name__ == "__main__":
    unittest.main()
