from pathlib import Path

path = Path("tests/test_logic_release.py")
text = path.read_text(encoding="utf-8")
old = '''        with (\n            patch("miniapp_api._authorize", AsyncMock(return_value=(tenant, {}))),\n            patch.object(database, "get_application", AsyncMock(return_value=app)),\n            patch.object(database, "get_available_interview_slots", AsyncMock(return_value=[])),\n            patch.object(database, "transition_application_status", AsyncMock()) as transition,\n        ):\n            with self.assertRaises(web.HTTPConflict):\n                await candidate_decision(request)\n        transition.assert_not_awaited()\n'''
new = '''        with (\n            patch("miniapp_api._authorize", AsyncMock(return_value=(tenant, {}))),\n            patch.object(database, "get_application", AsyncMock(return_value=app)),\n            patch.object(database, "get_available_interview_slots", AsyncMock(return_value=[])),\n            patch.object(database, "transition_application_status", AsyncMock()) as transition,\n            self.assertRaises(web.HTTPConflict),\n        ):\n            await candidate_decision(request)\n        transition.assert_not_awaited()\n'''
if old not in text:
    raise RuntimeError("Expected nested-with test block was not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("Logic release test lint cleanup applied.")
