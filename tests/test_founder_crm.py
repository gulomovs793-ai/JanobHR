import os
import tempfile
import unittest
from unittest.mock import patch

from services import database


class FounderCrmTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(
            database, "SQLITE_PATH", os.path.join(self.temp_dir.name, "crm.db")
        )
        self.path_patch.start()
        await database.init_db()
        self.tenant_a = await database.create_tenant("A", "ca", "aa", [11])
        self.tenant_b = await database.create_tenant("B", "cb", "ab", [22])

    async def asyncTearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    async def test_lead_status_accepts_only_allowlist(self):
        lead_id = await database.save_business_lead(
            telegram_user_id=11, contact_phone="+99890", company_name="A"
        )
        self.assertTrue(
            await database.update_business_lead_status(lead_id, "contacted")
        )
        self.assertFalse(await database.update_business_lead_status(lead_id, "admin"))
        lead = await database.get_business_lead(lead_id)
        self.assertEqual(lead["status"], "contacted")

    async def test_payment_lookup_is_tenant_isolated(self):
        await database.create_payment_order(
            self.tenant_a, "JH-PRIVATE", 299_000, 299_123, "2099-01-01T00:00:00+00:00"
        )
        self.assertIsNotNone(
            await database.get_payment_order_for_tenant(self.tenant_a, "JH-PRIVATE")
        )
        self.assertIsNone(
            await database.get_payment_order_for_tenant(self.tenant_b, "JH-PRIVATE")
        )

    async def test_notification_key_is_idempotent(self):
        self.assertFalse(await database.was_system_notification_sent("same"))
        await database.mark_system_notification_sent("same")
        await database.mark_system_notification_sent("same")
        self.assertTrue(await database.was_system_notification_sent("same"))


if __name__ == "__main__":
    unittest.main()
