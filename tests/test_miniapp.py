import asyncio
import hashlib
import hmac
import json
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlencode

from aiohttp import web

from miniapp_api import (
    add_interview_slot,
    billing_order_status,
    candidate_outcome,
    create_billing_order,
    create_vacancy,
    index,
    interviews,
    verify_init_data,
)
from services.plans import get_plan

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"


def signed_init_data(user_id: int, *, auth_date: int | None = None) -> str:
    values = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "query_id": "AA-test",
        "user": json.dumps({"id": user_id, "first_name": "Ali"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class MiniAppSecurityTests(unittest.TestCase):
    def test_valid_telegram_signature(self):
        result = verify_init_data(signed_init_data(777), TOKEN)
        self.assertEqual(result["user_id"], 777)

    def test_modified_user_is_rejected(self):
        data = signed_init_data(777).replace("777", "999")
        with self.assertRaises(web.HTTPUnauthorized):
            verify_init_data(data, TOKEN)

    def test_expired_session_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            verify_init_data(signed_init_data(777, auth_date=1), TOKEN, now=10_000)

    def test_wrong_bot_token_is_rejected(self):
        with self.assertRaises(web.HTTPUnauthorized):
            verify_init_data(signed_init_data(777), TOKEN + "x")

    def test_miniapp_index_rejects_non_numeric_tenant(self):
        request = type("Request", (), {"match_info": {"tenant_id": '\" onload=alert(1)'}})()
        with self.assertRaises(web.HTTPNotFound):
            asyncio.run(index(request))


class MiniAppWorkflowTests(unittest.IsolatedAsyncioTestCase):
    class JsonRequest:
        def __init__(self, payload, **match_info):
            self.payload = payload
            self.match_info = match_info

        async def json(self):
            return self.payload

    async def test_interviews_are_split_by_selected_slot(self):
        apps = [
            {
                "id": 1,
                "full_name": "Ali Test",
                "username": None,
                "phone_number": "+998900000000",
                "vacancy_key": "sales",
                "vacancy_title": "Sotuv menejeri",
                "status": "accepted",
                "ai_scores": {},
                "selected_slot": "2026-09-02 10:30",
                "created_at": "2026-09-01",
            },
            {
                "id": 2,
                "full_name": "Vali Test",
                "username": None,
                "phone_number": "+998911111111",
                "vacancy_key": "smm",
                "vacancy_title": "SMM mutaxassisi",
                "status": "accepted",
                "ai_scores": {},
                "selected_slot": None,
                "created_at": "2026-09-01",
            },
        ]
        request = object()
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch("miniapp_api.database.list_applications", AsyncMock(return_value=(apps, 2))),
            patch("miniapp_api.database.list_interview_slots", AsyncMock(return_value=[])),
            patch("miniapp_api.database.get_interview_settings", AsyncMock(return_value={})),
        ):
            response = await interviews(request)
        payload = json.loads(response.text)
        self.assertEqual(payload["total"], 2)
        self.assertEqual([item["id"] for item in payload["scheduled"]], [1])
        self.assertEqual([item["id"] for item in payload["awaiting_slot"]], [2])

    async def test_add_interview_slot_validates_and_saves(self):
        add_slot = AsyncMock(return_value=11)
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch("miniapp_api.database.list_interview_slots", AsyncMock(return_value=[])),
            patch("miniapp_api.database.add_interview_slot", add_slot),
        ):
            response = await add_interview_slot(
                self.JsonRequest({"label": "5-sentabr, 14:00", "capacity": 3})
            )
        payload = json.loads(response.text)
        self.assertEqual(payload["slot"]["id"], 11)
        add_slot.assert_awaited_once_with(7, "5-sentabr, 14:00", 3)

    async def test_add_interview_slot_rejects_invalid_capacity(self):
        with patch(
            "miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))
        ), self.assertRaises(web.HTTPBadRequest):
            await add_interview_slot(
                self.JsonRequest({"label": "5-sentabr, 14:00", "capacity": 0})
            )

    async def test_outcome_only_closes_accepted_candidate(self):
        app = {"id": 9, "status": "accepted"}
        transition = AsyncMock(return_value=True)
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch("miniapp_api.database.get_application", AsyncMock(return_value=app)),
            patch("miniapp_api.database.transition_application_status", transition),
        ):
            response = await candidate_outcome(
                self.JsonRequest({"outcome": "hired"}, app_id="9")
            )
        self.assertEqual(json.loads(response.text)["status"], "hired")
        transition.assert_awaited_once_with(7, 9, "hired", {"accepted"})

    async def test_create_vacancy_checks_plan_limit(self):
        payload = {
            "title": "Sotuv menejeri",
            "questions": ["Tajribangiz?", "Natijangiz?", "Rejangiz?"],
            "reject_message": "Arizangiz uchun rahmat.",
        }
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch(
                "miniapp_api.database.get_subscription_usage",
                AsyncMock(return_value={"vacancies_available": False}),
            ),self.assertRaises(web.HTTPPaymentRequired)
        ):
            await create_vacancy(self.JsonRequest(payload))

    async def test_create_billing_order_returns_exact_payment_details(self):
        create_order = AsyncMock(
            return_value={
                "order_code": "JH-TEST12",
                "amount": 599_117,
                "expires_at": "2099-01-01T00:00:00+00:00",
            }
        )
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch("miniapp_api.PAYMENT_CARD_NUMBER", "8600123412341234"),
            patch("miniapp_api.PAYMENT_CARD_HOLDER", "TEST USER"),
            patch(
                "miniapp_api.database.get_subscription_usage",
                AsyncMock(
                    return_value={
                        "plan": get_plan("start"),
                        "expired": False,
                        "expires_at": "2099-01-01T00:00:00+00:00",
                    }
                ),
            ),
            patch("miniapp_api.create_payment_order_for_plan", create_order),
        ):
            response = await create_billing_order(
                self.JsonRequest({"plan_code": "growth"})
            )
        payload = json.loads(response.text)
        self.assertEqual(response.status, 201)
        self.assertEqual(payload["order_code"], "JH-TEST12")
        self.assertEqual(payload["amount"], 599_117)
        self.assertEqual(payload["card_number"], "8600123412341234")
        create_order.assert_awaited_once_with(7, 599_000, plan_code="growth")

    async def test_create_billing_order_blocks_lower_active_plan(self):
        create_order = AsyncMock()
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch("miniapp_api.PAYMENT_CARD_NUMBER", "8600123412341234"),
            patch(
                "miniapp_api.database.get_subscription_usage",
                AsyncMock(
                    return_value={
                        "plan": get_plan("business"),
                        "expired": False,
                        "expires_at": "2099-01-01T00:00:00+00:00",
                    }
                ),
            ),
            patch("miniapp_api.create_payment_order_for_plan", create_order),
            self.assertRaises(web.HTTPConflict),
        ):
            await create_billing_order(self.JsonRequest({"plan_code": "start"}))
        create_order.assert_not_awaited()

    async def test_billing_order_status_is_tenant_scoped(self):
        with (
            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),
            patch(
                "miniapp_api.database.get_payment_order_for_tenant",
                AsyncMock(return_value=None),
            ),self.assertRaises(web.HTTPNotFound)
        ):
            await billing_order_status(
                self.JsonRequest({}, order_code="JH-OTHER")
            )


if __name__ == "__main__":
    unittest.main()
