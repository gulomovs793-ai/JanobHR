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

print("Remaining release lint debt cleaned.")
