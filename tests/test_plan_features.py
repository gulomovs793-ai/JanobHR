import unittest

from handlers.admin import format_candidate_card
from services.plans import (
    FEATURE_ADVANCED_REPORTING,
    FEATURE_AUTO_INTERVIEW_REMINDERS,
    FEATURE_FUNNEL_ANALYTICS,
    FEATURE_RISK_SIGNALS,
    FEATURE_TOP_CANDIDATE_COMPARE,
    has_feature,
    market_feature_labels,
    minimum_plan_for_feature,
)


def scored(score: int, flags=None) -> dict:
    return {
        "score": score,
        "verdict": "yashil" if score >= 75 else "sariq",
        "natijadorlik": score,
        "masuliyat": score,
        "aniqlik": score,
        "relevant": True,
        "red_flags": flags or [],
        "izoh": "Qisqa izoh",
        "evidence": "Aniq natija",
    }


class PlanFeatureTests(unittest.TestCase):
    def test_start_keeps_core_but_not_growth_intelligence(self):
        self.assertFalse(has_feature("start", FEATURE_RISK_SIGNALS))
        self.assertFalse(has_feature("start", FEATURE_TOP_CANDIDATE_COMPARE))
        self.assertFalse(has_feature("start", FEATURE_FUNNEL_ANALYTICS))
        self.assertFalse(has_feature("start", FEATURE_AUTO_INTERVIEW_REMINDERS))

    def test_growth_unlocks_intelligence_but_not_business_reporting(self):
        self.assertTrue(has_feature("growth", FEATURE_RISK_SIGNALS))
        self.assertTrue(has_feature("growth", FEATURE_TOP_CANDIDATE_COMPARE))
        self.assertTrue(has_feature("growth", FEATURE_FUNNEL_ANALYTICS))
        self.assertTrue(has_feature("growth", FEATURE_AUTO_INTERVIEW_REMINDERS))
        self.assertFalse(has_feature("growth", FEATURE_ADVANCED_REPORTING))

    def test_business_unlocks_advanced_reporting(self):
        self.assertTrue(has_feature("business", FEATURE_ADVANCED_REPORTING))
        self.assertEqual(minimum_plan_for_feature(FEATURE_ADVANCED_REPORTING), "business")

    def test_billing_feature_lists_are_differentiated(self):
        start = market_feature_labels("start")
        growth = market_feature_labels("growth")
        business = market_feature_labels("business")
        self.assertGreater(len(growth), len(start))
        self.assertNotEqual(growth, business)
        self.assertIn("Priority support", business)

    def test_start_card_does_not_expose_red_flag_details(self):
        app = {
            "full_name": "Test Nomzod",
            "vacancy_title": "Sotuvchi",
            "phone_number": "+998",
            "ai_scores": {"q": scored(82, ["qurbon_sindromi"])},
        }
        locked = format_candidate_card(app, show_risks=False)
        premium = format_candidate_card(app, show_risks=True)
        self.assertIn("GROWTH", locked)
        self.assertNotIn("Qurbon sindromi", locked)
        self.assertIn("Qurbon sindromi", premium)


if __name__ == "__main__":
    unittest.main()
