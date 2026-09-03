from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Expected cleanup block not found in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "admin_bot/handlers_interview.py",
    '''    try:\n        await callback.message.edit_reply_markup(reply_markup=None)\n    except Exception:\n        pass\n    await callback.answer(f"✅ {labels[outcome]}")\n''',
    '''    try:\n        await callback.message.edit_reply_markup(reply_markup=None)\n    except Exception:  # noqa: BLE001 - natija DBda saqlangan; eski xabarni edit qilish kritik emas\n        await callback.answer(f"✅ {labels[outcome]}")\n        return\n    await callback.answer(f"✅ {labels[outcome]}")\n''',
)

print("Janob HR 2 CI cleanup applied.")
