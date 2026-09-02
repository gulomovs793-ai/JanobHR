import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from services import database
from services.payment_automation import handle_payment_notification
from services.plans import get_plan_transition


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

    async def test_active_plan_transition_rules_are_ordered(self):
        self.assertEqual(
            get_plan_transition("growth", "start", current_expired=False),
            "blocked",
        )
        self.assertEqual(
            get_plan_transition("growth", "growth", current_expired=False),
            "renew",
        )
        self.assertEqual(
            get_plan_transition("growth", "business", current_expired=False),
            "upgrade",
        )
        self.assertEqual(
            get_plan_transition("business", "start", current_expired=True),
            "select",
        )

    async def test_database_refuses_active_plan_downgrade(self):
        await database.activate_subscription(self.tenant_id, "business")
        with self.assertRaises(ValueError):
            await database.activate_subscription(self.tenant_id, "start")
        tenant = await database.get_tenant(self.tenant_id)
        self.assertEqual(tenant["plan_code"], "business")

    async def test_stale_lower_plan_payment_requires_review(self):
        await database.activate_subscription(self.tenant_id, "business")
        order_id = await database.create_payment_order(
            self.tenant_id,
            "JH-LOWER",
            299_000,
            299_123,
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
                "+ 299 123 so'm karta **1234", notify, activate
            )
        self.assertEqual(result["status"], "needs_review")
        activate.assert_not_awaited()
        order = await database.get_payment_order_by_code("JH-LOWER")
        self.assertEqual(order["id"], order_id)
        self.assertEqual(order["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
