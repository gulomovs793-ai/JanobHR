import unittest
from unittest.mock import AsyncMock

from services.payment_automation import (
    handle_payment_notification,
    looks_like_non_payment_summary,
    parse_notification_amount,
)


class PaymentNotificationTests(unittest.IsolatedAsyncioTestCase):
    def test_cardxabar_balance_summary_is_not_a_payment(self):
        text = (
            "💳 Umumiy balans:\n"
            "💰 108.17 so'm\n\n"
            "💳 Karta: 561468*******9304\n"
            "🏦 Bank: HAMKORBANK\n"
            "👤 GULOMOV SHAXRIYOR\n"
            "💸 108.17 so'm\n\n"
            "💳 Karta: 561468*******3533\n"
            "🏦 Bank: TBC Bank\n"
            "💸 0.00 so'm"
        )

        self.assertTrue(looks_like_non_payment_summary(text))
        self.assertIsNone(parse_notification_amount(text))

    def test_cardxabar_incoming_amount_beats_balance(self):
        text = (
            "🟢 Perevod na kartu\n"
            "➕ 1 183.00 UZS\n"
            "💳 ****9304\n"
            "📍 UB P2P HUMO2UZCARD, UZ\n"
            "🕘 22.08.26 14:47\n"
            "💵 1 291.17 UZS"
        )

        self.assertFalse(looks_like_non_payment_summary(text))
        self.assertEqual(parse_notification_amount(text), 1183)

    async def test_balance_summary_never_notifies_founder(self):
        text = (
            "💳 Umumiy balans:\n"
            "💰 108.17 so'm\n"
            "💳 Karta: 561468*******9304\n"
            "🏦 Bank: HAMKORBANK"
        )
        notify = AsyncMock()
        activate = AsyncMock()

        result = await handle_payment_notification(text, notify, activate)

        self.assertEqual(result["status"], "ignored_non_payment")
        notify.assert_not_awaited()
        activate.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
