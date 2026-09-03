from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected block not found in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "config.py",
    '            raise ValueError("settings bundle must be an object")\n',
    '            raise TypeError("settings bundle must be an object")\n',
)

replace_once(
    "tests/test_miniapp.py",
    '''            patch("miniapp_api.create_payment_order_for_plan", create_order),\n        ):\n            with self.assertRaises(web.HTTPConflict):\n                await create_billing_order(self.JsonRequest({"plan_code": "start"}))\n''',
    '''            patch("miniapp_api.create_payment_order_for_plan", create_order),\n            self.assertRaises(web.HTTPConflict),\n        ):\n            await create_billing_order(self.JsonRequest({"plan_code": "start"}))\n''',
)

# Mini App outcome endi oddiy update emas, atomik state transition ishlatadi.
replace_once(
    "tests/test_miniapp.py",
    '''        update = AsyncMock()\n        with (\n            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),\n            patch("miniapp_api.database.get_application", AsyncMock(return_value=app)),\n            patch("miniapp_api.database.update_status", update),\n        ):\n            response = await candidate_outcome(\n                self.JsonRequest({"outcome": "hired"}, app_id="9")\n            )\n        self.assertEqual(json.loads(response.text)["status"], "hired")\n        update.assert_awaited_once_with(7, 9, "hired")\n''',
    '''        transition = AsyncMock(return_value=True)\n        with (\n            patch("miniapp_api._authorize", AsyncMock(return_value=({"id": 7}, {}))),\n            patch("miniapp_api.database.get_application", AsyncMock(return_value=app)),\n            patch("miniapp_api.database.transition_application_status", transition),\n        ):\n            response = await candidate_outcome(\n                self.JsonRequest({"outcome": "hired"}, app_id="9")\n            )\n        self.assertEqual(json.loads(response.text)["status"], "hired")\n        transition.assert_awaited_once_with(7, 9, "hired", {"accepted"})\n''',
)

# Parserning o'zi ham balans/karta summary xabarini to'lov deb qaytarmasin.
replace_once(
    "services/payment_automation.py",
    '''    raw = text or ""\n\n    for line in raw.splitlines():\n''',
    '''    raw = text or ""\n    if looks_like_non_payment_summary(raw):\n        return None\n\n    for line in raw.splitlines():\n''',
)

print("Remaining release lint/test debt cleaned.")
