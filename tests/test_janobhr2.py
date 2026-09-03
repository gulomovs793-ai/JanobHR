import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from services import database
from services.ai_scoring import score_answer
from services.hiring_intelligence import (
    candidate_risks,
    compare_candidates,
    extract_salary_expectation,
    hiring_funnel,
)


def scored(score: int, *, evidence: str = "Aniq natija keltirdi", flags=None) -> dict:
    return {
        "score": score,
        "verdict": "yashil" if score >= 75 else "sariq" if score >= 50 else "qizil",
        "natijadorlik": score,
        "masuliyat": score,
        "aniqlik": score,
        "relevant": True,
        "red_flags": flags or [],
        "izoh": "Qisqa izoh",
        "evidence": evidence,
    }


class HiringIntelligenceTests(unittest.TestCase):
    def test_salary_parser_understands_mln(self):
        result = extract_salary_expectation({"salary_expectation": "8 mln so'm"})
        self.assertEqual(result["amount"], 8_000_000)
        self.assertEqual(result["currency"], "UZS")

    def test_salary_budget_becomes_non_blocking_risk(self):
        app = {
            "ai_scores": {"achievement": scored(82)},
            "ai_suspect_flags": [],
            "answers": {"salary_expectation": "10 mln so'm"},
        }
        risks = candidate_risks(app, {"profile": {"salary_budget_max": 8_000_000}})
        self.assertIn("maosh_budgetdan_yuqori", {item["code"] for item in risks})

    def test_compare_candidates_ranks_best_score_first(self):
        apps = [
            {
                "id": 1,
                "full_name": "A",
                "status": "pending",
                "created_at": "2026-09-03T01:00:00+00:00",
                "answers": {},
                "ai_scores": {"q": scored(72, evidence="Yaxshi misol")},
                "ai_suspect_flags": [],
            },
            {
                "id": 2,
                "full_name": "B",
                "status": "pending",
                "created_at": "2026-09-03T02:00:00+00:00",
                "answers": {},
                "ai_scores": {"q": scored(91, evidence="Rejani 130% bajargan")},
                "ai_suspect_flags": [],
            },
        ]
        result = compare_candidates(apps, {"profile": {}}, limit=3)
        self.assertEqual(result["items"][0]["id"], 2)
        self.assertIn("B", result["recommendation"]["text"])

    def test_hiring_funnel_uses_pipeline_statuses(self):
        apps = [
            {"status": "pending", "ai_scores": {"q": scored(80)}},
            {"status": "rejected_hard_filter", "ai_scores": {}},
            {"status": "accepted", "ai_scores": {"q": scored(85)}},
            {"status": "hired", "ai_scores": {"q": scored(88)}},
            {"status": "no_show", "ai_scores": {"q": scored(70)}},
        ]
        funnel = hiring_funnel(apps)
        self.assertEqual(funnel["applications"], 5)
        self.assertEqual(funnel["passed_filter"], 4)
        self.assertEqual(funnel["strong"], 3)
        self.assertEqual(funnel["interview"], 3)
        self.assertEqual(funnel["hired"], 1)
        self.assertEqual(funnel["no_show"], 1)


class EvidenceScoringTests(unittest.IsolatedAsyncioTestCase):
    async def test_score_answer_keeps_evidence(self):
        payload = json.dumps(
            {
                "relevant": True,
                "natijadorlik": 90,
                "masuliyat": 80,
                "aniqlik": 85,
                "verdict": "yashil",
                "red_flags": [],
                "izoh": "Natija raqam bilan ko'rsatilgan.",
                "evidence": "Bir oyda rejaning 118 foizini bajargan.",
            }
        )
        with patch("services.ai_scoring._call_ai", AsyncMock(return_value=payload)):
            result = await score_answer("Eng katta yutug'ingiz?", "Rejani 118% bajardim")
        self.assertEqual(result["evidence"], "Bir oyda rejaning 118 foizini bajargan.")
        self.assertEqual(result["score"], 85)


class JanobHR2DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "janobhr2.db")
        self.path_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.path_patch.start()
        await database.init_db()
        self.tenant_id = await database.create_tenant(
            "JH2 Test", "candidate-token-2", "admin-token-2", [123]
        )

    async def asyncTearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    async def test_onboarding_profile_and_vacancy_profile_persist(self):
        await database.update_tenant_onboarding(
            self.tenant_id,
            industry="Retail",
            profile={"ideal_candidate": "Natijador sotuvchi"},
        )
        tenant = await database.get_tenant(self.tenant_id)
        self.assertEqual(tenant["industry"], "Retail")
        self.assertEqual(tenant["onboarding_profile"]["ideal_candidate"], "Natijador sotuvchi")
        self.assertTrue(tenant["onboarding_completed_at"])

        await database.create_vacancy(
            tenant_id=self.tenant_id,
            key="sales_jh2",
            title="Sotuv menejeri",
            reject_message="Rahmat, hozircha keyingi bosqichga o'tmadingiz.",
            questions=[{"key": "q1", "text": "Natijangiz?", "ai_score": True}],
            resume_required=False,
            profile={"salary_budget_max": 8_000_000},
        )
        vacancy = await database.get_vacancy(self.tenant_id, "sales_jh2")
        self.assertEqual(vacancy["profile"]["salary_budget_max"], 8_000_000)

    async def test_interview_slot_can_store_machine_readable_time(self):
        starts_at = "2026-09-05T05:00:00+00:00"
        slot_id = await database.add_interview_slot(
            self.tenant_id, "2026-09-05 10:00", 2, starts_at=starts_at
        )
        slots = await database.list_interview_slots(self.tenant_id)
        slot = next(item for item in slots if item["id"] == slot_id)
        self.assertEqual(slot["starts_at"], starts_at)


if __name__ == "__main__":
    unittest.main()
