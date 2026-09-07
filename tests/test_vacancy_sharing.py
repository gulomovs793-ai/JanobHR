import unittest
from pathlib import Path

from admin_bot.handlers_vacancy_list import _vacancy_link


class VacancySharingTests(unittest.TestCase):
    def test_link_targets_customer_candidate_bot_and_exact_vacancy(self):
        self.assertEqual(
            _vacancy_link("acme_hr_bot", "sotuvchi"),
            "https://t.me/acme_hr_bot?start=vac_sotuvchi",
        )

    def test_admin_share_and_candidate_deep_link_flow_are_wired(self):
        admin_source = Path("admin_bot/handlers_vacancy_list.py").read_text(
            encoding="utf-8"
        )
        start_source = Path("handlers/start.py").read_text(encoding="utf-8")
        vacancy_source = Path("handlers/vacancy.py").read_text(encoding="utf-8")
        requirements = Path("requirements.txt").read_text(encoding="utf-8")

        self.assertIn('callback_data=f"vacshare:{key}"', admin_source)
        self.assertIn("qrcode.QRCode", admin_source)
        self.assertIn("?start=vac_", admin_source)
        self.assertIn('payload.startswith("vac_")', start_source)
        self.assertIn("pending_vacancy_key", start_source)
        self.assertIn("begin_vacancy_application", start_source)
        self.assertIn("ask_resume_upfront", vacancy_source)
        self.assertIn("qrcode[pil]==8.2", requirements)


if __name__ == "__main__":
    unittest.main()
