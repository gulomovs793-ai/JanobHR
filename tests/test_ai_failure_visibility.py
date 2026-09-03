import unittest

from handlers.admin import format_candidate_card
from services.ai_scoring import (
    aggregate_scores,
    clear_ai_unavailable,
    get_ai_unavailable_keys,
    mark_ai_unavailable,
)


class AIFailureVisibilityTests(unittest.TestCase):
    def _app(self, ai_scores: dict) -> dict:
        return {
            "full_name": "Test Nomzod",
            "vacancy_title": "Sotuv menejeri",
            "phone_number": "+998000000000",
            "ai_scores": ai_scores,
        }

    def test_total_ai_failure_is_explicit_on_candidate_card(self):
        scores = mark_ai_unavailable({}, "achievement")
        card = format_candidate_card(self._app(scores))
        self.assertIn("AI ishlamadi", card)
        self.assertIn("AI tahlili 1 ta savolda ishlamadi", card)
        self.assertNotIn("Baholanmagan", card)

    def test_partial_ai_failure_preserves_real_score_and_warns(self):
        scored = {
            "score": 82,
            "verdict": "yashil",
            "natijadorlik": 80,
            "masuliyat": 84,
            "aniqlik": 82,
            "relevant": True,
            "red_flags": [],
            "izoh": "Aniq javob",
            "evidence": "Aniq natija ko'rsatgan",
        }
        scores = {"achievement": scored}
        scores = mark_ai_unavailable(scores, "mistake_lesson")
        aggregate = aggregate_scores(scores)
        self.assertIsNotNone(aggregate)
        self.assertEqual(aggregate["avg_score"], 82)
        card = format_candidate_card(self._app(scores))
        self.assertIn("82/100 ⚠️ qisman", card)
        self.assertIn("AI tahlili 1 ta savolda ishlamadi", card)

    def test_successful_retry_clears_failure_marker(self):
        scores = mark_ai_unavailable({}, "achievement")
        self.assertEqual(get_ai_unavailable_keys(scores), ["achievement"])
        scores = clear_ai_unavailable(scores, "achievement")
        self.assertEqual(get_ai_unavailable_keys(scores), [])

    def test_failed_followup_marker_removes_stale_score(self):
        scores = {
            "achievement": {
                "score": 45,
                "verdict": "qizil",
                "natijadorlik": 40,
                "masuliyat": 50,
                "aniqlik": 45,
            }
        }
        scores = mark_ai_unavailable(scores, "achievement")
        self.assertNotIn("achievement", scores)
        self.assertEqual(get_ai_unavailable_keys(scores), ["achievement"])


if __name__ == "__main__":
    unittest.main()
