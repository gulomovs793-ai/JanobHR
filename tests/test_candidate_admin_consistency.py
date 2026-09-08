import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from handlers.admin import build_candidate_analysis
from handlers.questions import _process_answer
from handlers.sell import maybe_send_sell_pitch
from services.ai_scoring import candidate_recommendation, mark_ai_unavailable


def score(value=82, flags=None):
    return dict(score=value, natijadorlik=value, amaliylik=value,
                masuliyat=value, aniqlik=value, red_flags=flags or [], relevant=True)


class CandidateAnalysisTests(unittest.TestCase):
    def test_recommendation_uses_aggregate_verdict_with_risks(self):
        self.assertTrue(candidate_recommendation({'q': score(90, ['javob_zid'])}).startswith('🟡'))
        self.assertTrue(candidate_recommendation({'q': score(52)}).startswith('🟡'))

    def test_missing_expected_score_is_visible(self):
        result = build_candidate_analysis({'ai_scores': {'q': score()}},
                                          {'questions': [{'key': 'q', 'text': 'Test', 'ai_score': True}]})
        self.assertTrue(result['partial_ai'])  # reference_check is also expected
        self.assertEqual(result['missing_ai_count'], 1)
        self.assertTrue(result['recommendation'].startswith('⚪'))

    def test_failed_analysis_does_not_recommend_interview(self):
        scores = mark_ai_unavailable({'q': score()}, 'other')
        self.assertTrue(candidate_recommendation(scores).startswith('⚪'))


class CandidateFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_followup_preserves_original_answer_and_scores_both(self):
        data = dict(question_index=0, vacancy_questions=[{'key': 'q', 'text': 'Plan?', 'ai_score': True}],
                    awaiting_followup_for=0, answers={'q': 'Original plan'}, ai_scores={})
        state = SimpleNamespace(get_data=AsyncMock(return_value=data), update_data=AsyncMock())
        message = SimpleNamespace(answer=AsyncMock())
        with patch('handlers.questions.score_answer', AsyncMock(return_value=score())) as scoring, patch('handlers.questions.ask_current_question', AsyncMock()):
            await _process_answer(message, state, 'More detail')
        scoring.assert_awaited_once_with('Plan?', 'Original plan\n\nMore detail')
        self.assertEqual(state.update_data.call_args.kwargs['answers']['q'], 'Original plan\n\nMore detail')

    async def test_partial_scores_do_not_trigger_automatic_invite(self):
        message = SimpleNamespace(answer=AsyncMock())
        with patch('handlers.sell.database.get_available_interview_slots', AsyncMock()) as slots:
            await maybe_send_sell_pitch(message, 1, 2, mark_ai_unavailable({'q': score(95)}, 'other'))
        slots.assert_not_awaited()
        message.answer.assert_not_awaited()
