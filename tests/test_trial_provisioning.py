import unittest
from pathlib import Path


class TrialProvisioningRegressionTests(unittest.TestCase):
    def test_create_bot_activates_after_two_tokens(self):
        source = Path("handlers/create_bot.py").read_text(encoding="utf-8")
        self.assertIn("activation = await activate_tenant(tenant_id)", source)
        self.assertIn("Ikkala botingiz ham ishga tushdi", source)
        self.assertIn("if not activation.get(\"ok\")", source)

    def test_setup_bot_activates_after_two_tokens(self):
        source = Path("setup_bot.py").read_text(encoding="utf-8")
        self.assertIn("activation = await activate_tenant(tenant_id)", source)
        self.assertIn("Ikkala botingiz ham ishga tushdi", source)
        self.assertIn("if not activation.get(\"ok\")", source)

    def test_startup_reconciles_old_pending_trials(self):
        source = Path("webhook_app.py").read_text(encoding="utf-8")
        self.assertIn('database.list_tenants(status="pending")', source)
        self.assertIn('result = await activate_tenant(pending["id"])', source)
        self.assertIn('pending.get("plan_code") != "trial"', source)


if __name__ == "__main__":
    unittest.main()
