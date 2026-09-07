import os
import tempfile
import unittest
import aiosqlite
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from partner_bot import main_menu
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

    def test_partner_application_review_is_founder_bot_owned(self):
        source = Path("partner_bot.py").read_text(encoding="utf-8")
        self.assertIn("FOUNDER_BOT_TOKEN", source)
        self.assertIn('callback_data=f"fp:partnerapprove:{partner_id}"', source)
        self.assertIn('"partners": "🤝 Hamkorlar uchun arizalar"', Path("founder_panel.py").read_text(encoding="utf-8"))

    def test_business_leads_are_routed_to_founder_bot(self):
        source = Path("handlers/create_bot.py").read_text(encoding="utf-8")
        self.assertIn("async def _send_to_founder_bot", source)
        self.assertIn("FOUNDER_BOT_TOKEN", source)

    def test_payout_notifications_and_actions_are_founder_owned(self):
        source = Path("partner_payout_bot.py").read_text(encoding="utf-8")
        self.assertIn("founder_payout_router = Router", source)
        self.assertIn("token=FOUNDER_BOT_TOKEN", source)
        self.assertIn("To'lov tasdig'i chek sifatida yuborildi", source)

    def test_partner_menu_has_clear_operational_order(self):
        rows = [[button.text for button in row] for row in main_menu().keyboard]
        self.assertEqual(
            rows,
            [
                ["📱 Boshqaruv paneli"],
                ["📊 Statistika", "💰 Komissiya"],
                ["🔗 Referral link", "🎟 Promo kod"],
                ["💸 Pul yechish"],
                ["📦 Reklama materiallari"],
                ["❓ Tez-tez so'raladigan savollar", "🆘 Yordam"],
            ],
        )


class PartnerAttributionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "partner.db")
        self.patch = patch.object(pdb, "SQLITE_PATH", self.db_path)
        self.patch.start()
        self.payout_patch = patch.object(partner_payouts, "SQLITE_PATH", self.db_path)
        self.payout_patch.start()
        await pdb.init_partner_db()
        await partner_payouts.init_partner_payout_db()

    async def asyncTearDown(self):
        self.patch.stop()
        self.payout_patch.stop()
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

    async def test_payout_request_stores_explicit_payment_identity(self):
        partner = await pdb.upsert_application(
            user_id=555,
            full_name="Partner User",
            username="partner_user",
            phone="+998901234567",
            role="blogger",
            has_business_clients=True,
            client_band="1-3",
        )
        partner = await pdb.set_partner_status(partner["id"], "approved")
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """
                CREATE TABLE tenants (
                    id INTEGER PRIMARY KEY,
                    company_name TEXT,
                    contact_name TEXT,
                    contact_phone TEXT,
                    contact_username TEXT
                )
                """
            )
            await db.execute("INSERT INTO tenants(id, company_name) VALUES (7, 'Acme')")
            await db.execute(
                """
                INSERT INTO partner_referral_events(
                    partner_id, event_type, tenant_id, plan_code, amount,
                    commission_amount, metadata, created_at
                ) VALUES (?, 'sale', 7, 'start', 299000, 69100, ?, ?)
                """,
                (
                    partner["id"],
                    '{"discount_type":"percent","discount_value":10,"discount_amount":29900,"base_commission":99000}',
                    "2026-09-01T00:00:00+00:00",
                ),
            )
            await db.commit()

        result = await partner_payouts.create_payout_request(
            partner["id"],
            "Jasur Karimov",
            "8600 1234 5678 9012",
            "@janobhr",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["payout_full_name"], "Jasur Karimov")
        self.assertEqual(result["payout_card_number"], "8600123456789012")
        self.assertEqual(result["receipt_telegram_username"], "@janobhr")
        self.assertEqual(result["requested_amount"], 69100)
        self.assertEqual(result["total_amount"], 69100)

    async def test_payout_request_rejects_invalid_payment_identity(self):
        result = await partner_payouts.create_payout_request(
            1, "Jasur", "1234", "janobhr"
        )
        self.assertFalse(result["ok"])
        self.assertIn("ism va familiya", result["error"].lower())


if __name__ == "__main__":
    unittest.main()
