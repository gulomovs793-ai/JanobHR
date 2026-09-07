import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from services import partner_database as pdb
from services import partner_payouts
from services.partner_links import build_referral_link


class PartnerRulesTests(unittest.TestCase):
    def test_commission_uses_plan_price_for_percent_discount(self):
        result = pdb.calculate_partner_payout("start", 10)
        self.assertEqual(result["discount_amount"], 29_900)
        self.assertEqual(result["commission_amount"], 69_100)
        self.assertEqual(result["discounted_base_amount"], 269_100)

    def test_fixed_discount_cannot_exceed_commission(self):
        result = pdb.calculate_partner_payout(
            "growth", discount_type="amount", discount_value=30_000
        )
        self.assertEqual(result["commission_amount"], 169_000)
        with self.assertRaises(ValueError):
            pdb.calculate_partner_payout(
                "start", discount_type="amount", discount_value=99_001
            )

    def test_referral_link_is_main_bot_link(self):
        self.assertEqual(
            build_referral_link("janobHR_bot", "ABC123"),
            "https://t.me/janobHR_bot?start=ref_ABC123",
        )
        self.assertEqual(build_referral_link("", "ABC123"), "")

    def test_payout_dates_skip_sunday_and_holiday(self):
        with patch.dict(os.environ, {"PARTNER_PAYOUT_HOLIDAYS": "2026-09-01"}):
            self.assertEqual(
                partner_payouts.adjust_payout_date(date(2026, 9, 1)),
                date(2026, 9, 2),
            )
        self.assertEqual(
            partner_payouts.adjust_payout_date(date(2026, 8, 2)),
            date(2026, 8, 3),
        )

    def test_delay_bonus_ignores_sunday(self):
        due = date(2026, 8, 1)
        now = datetime(2026, 8, 4, 12, tzinfo=timezone.utc)
        info = partner_payouts.payout_delay_info(due, now)
        self.assertEqual(info["delay_days"], 2)
        self.assertEqual(info["bonus_amount"], 6_000)


class PartnerAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "partner.db")
        self.patch = patch.object(pdb, "SQLITE_PATH", self.db_path)
        self.patch.start()
        await pdb.init_partner_db()

    async def asyncTearDown(self):
        self.patch.stop()
        self.temp_dir.cleanup()

    async def test_first_promo_claim_locks_tenant_to_partner(self):
        first = await pdb.claim_tenant_attribution(
            77, 1, source="promo_code", promo_code="A10"
        )
        second = await pdb.claim_tenant_attribution(
            77, 2, source="promo_code", promo_code="B10"
        )
        self.assertEqual(first["partner_id"], 1)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
