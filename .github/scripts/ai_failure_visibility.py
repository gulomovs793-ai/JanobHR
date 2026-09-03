from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# Central metadata helpers. The metadata lives inside ai_scores but aggregate_scores
# already ignores dictionaries without a numeric `score`, so it cannot distort hiring scores.
aggregate_anchor = '''class AggregateResult(TypedDict):\n'''
aggregate_insert = '''AI_STATUS_KEY = "__ai_status__"\n\n\ndef get_ai_unavailable_keys(ai_scores: dict | None) -> list[str]:\n    meta = (ai_scores or {}).get(AI_STATUS_KEY)\n    if not isinstance(meta, dict):\n        return []\n    keys = meta.get("unavailable_keys")\n    if not isinstance(keys, list):\n        return []\n    return [str(key) for key in keys if str(key)]\n\n\ndef mark_ai_unavailable(ai_scores: dict | None, question_key: str) -> dict:\n    scores = dict(ai_scores or {})\n    # If a follow-up answer replaced an older scored answer but the re-analysis\n    # failed, never keep the stale old score attached to the new answer.\n    scores.pop(question_key, None)\n    keys = get_ai_unavailable_keys(scores)\n    if question_key not in keys:\n        keys.append(question_key)\n    scores[AI_STATUS_KEY] = {"unavailable_keys": keys}\n    return scores\n\n\ndef clear_ai_unavailable(ai_scores: dict | None, question_key: str) -> dict:\n    scores = dict(ai_scores or {})\n    keys = [key for key in get_ai_unavailable_keys(scores) if key != question_key]\n    if keys:\n        scores[AI_STATUS_KEY] = {"unavailable_keys": keys}\n    else:\n        scores.pop(AI_STATUS_KEY, None)\n    return scores\n\n\nclass AggregateResult(TypedDict):\n'''
replace_once(
    "services/ai_scoring.py",
    aggregate_anchor,
    aggregate_insert,
    "AI availability metadata helpers",
)

# Candidate flow: record an explicit failure marker instead of silently omitting a score.
replace_once(
    "handlers/questions.py",
    "from services.ai_scoring import check_relevance, score_answer\n",
    '''from services.ai_scoring import (\n    check_relevance,\n    clear_ai_unavailable,\n    mark_ai_unavailable,\n    score_answer,\n)\n''',
    "questions AI imports",
)

followup_old = '''        result = await score_answer(q["text"], answer_text)\n        if result is not None:\n            ai_scores[q["key"]] = result\n\n            if "ai_yozgan" in result.get("red_flags", []):\n'''
followup_new = '''        result = await score_answer(q["text"], answer_text)\n        if result is None:\n            ai_scores = mark_ai_unavailable(ai_scores, q["key"])\n        else:\n            ai_scores = clear_ai_unavailable(ai_scores, q["key"])\n            ai_scores[q["key"]] = result\n\n        if result is not None:\n            if "ai_yozgan" in result.get("red_flags", []):\n'''
replace_once(
    "handlers/questions.py",
    followup_old,
    followup_new,
    "follow-up AI failure marker",
)

normal_old = '''    if q.get("ai_score"):\n        result = await score_answer(q["text"], answer_text)\n        if result is not None:\n            ai_scores[q["key"]] = result\n            relevant = result.get("relevant", True)\n'''
normal_new = '''    if q.get("ai_score"):\n        result = await score_answer(q["text"], answer_text)\n        if result is None:\n            ai_scores = mark_ai_unavailable(ai_scores, q["key"])\n        else:\n            ai_scores = clear_ai_unavailable(ai_scores, q["key"])\n            ai_scores[q["key"]] = result\n            relevant = result.get("relevant", True)\n'''
replace_once(
    "handlers/questions.py",
    normal_old,
    normal_new,
    "normal AI failure marker",
)

# Admin UI: make a full or partial AI outage impossible to miss on the first card.
replace_once(
    "handlers/admin.py",
    "from services.ai_scoring import aggregate_scores\n",
    "from services.ai_scoring import aggregate_scores, get_ai_unavailable_keys\n",
    "admin AI metadata import",
)

card_old = '''def format_candidate_card(app: dict) -> str:\n    aggregate = aggregate_scores(app.get("ai_scores") or {})\n    scored = [\n        value\n        for value in (app.get("ai_scores") or {}).values()\n        if isinstance(value, dict) and isinstance(value.get("score"), (int, float))\n    ]\n    strongest = max(scored, key=lambda value: value["score"], default=None)\n    weakest = min(scored, key=lambda value: value["score"], default=None)\n    strength = (strongest or {}).get("evidence") or (strongest or {}).get("izoh") or "Javoblarini to'liq ko'rib chiqing."\n    risk = "Aniq xavf aniqlanmadi."\n    if aggregate and aggregate.get("red_flags"):\n        risk = _RED_FLAG_LABELS.get(\n            aggregate["red_flags"][0], aggregate["red_flags"][0]\n        )\n    elif weakest and weakest.get("score", 100) < 70:\n        risk = weakest.get("izoh") or "Ayrim javoblari yetarlicha aniq emas."\n    score = f"{aggregate['avg_score']}/100" if aggregate else "Baholanmagan"\n'''
card_new = '''def format_candidate_card(app: dict) -> str:\n    ai_scores = app.get("ai_scores") or {}\n    aggregate = aggregate_scores(ai_scores)\n    unavailable_keys = get_ai_unavailable_keys(ai_scores)\n    scored = [\n        value\n        for value in ai_scores.values()\n        if isinstance(value, dict) and isinstance(value.get("score"), (int, float))\n    ]\n    strongest = max(scored, key=lambda value: value["score"], default=None)\n    weakest = min(scored, key=lambda value: value["score"], default=None)\n    strength = (strongest or {}).get("evidence") or (strongest or {}).get("izoh") or "Javoblarini to'liq ko'rib chiqing."\n    risk = "Aniq xavf aniqlanmadi."\n    if aggregate and aggregate.get("red_flags"):\n        risk = _RED_FLAG_LABELS.get(\n            aggregate["red_flags"][0], aggregate["red_flags"][0]\n        )\n    elif weakest and weakest.get("score", 100) < 70:\n        risk = weakest.get("izoh") or "Ayrim javoblari yetarlicha aniq emas."\n\n    if unavailable_keys:\n        ai_note = f"⚠️ AI tahlili {len(unavailable_keys)} ta savolda ishlamadi."\n        risk = f"{ai_note} {risk}"\n        if aggregate:\n            score = f"{aggregate['avg_score']}/100 ⚠️ qisman"\n        else:\n            score = "⚠️ AI ishlamadi"\n            strength = "AI tahlili mavjud emas — javoblarni qo'lda ko'ring."\n    else:\n        score = f"{aggregate['avg_score']}/100" if aggregate else "Baholanmagan"\n'''
replace_once(
    "handlers/admin.py",
    card_old,
    card_new,
    "candidate card AI failure visibility",
)

replace_once(
    "handlers/admin.py",
    '''    ai_scores = app.get("ai_scores") or {}\n    tenant_id = app["tenant_id"]\n''',
    '''    ai_scores = app.get("ai_scores") or {}\n    unavailable_keys = get_ai_unavailable_keys(ai_scores)\n    tenant_id = app["tenant_id"]\n''',
    "full text AI metadata",
)

full_old = '''        lines.append(\n            f"{emoji} <b>Yakuniy AI ball: {aggregate['avg_score']}/100</b>{coverage}"\n        )\n        lines.append(\n            f"📊 Natijadorlik: {aggregate['avg_natijadorlik']} | "\n'''
full_new = '''        lines.append(\n            f"{emoji} <b>Yakuniy AI ball: {aggregate['avg_score']}/100</b>{coverage}"\n        )\n        if unavailable_keys or valid_count < len(expected_keys):\n            missing_count = max(len(expected_keys) - valid_count, len(unavailable_keys))\n            lines.append(\n                f"⚠️ <b>AI tahlili to'liq emas:</b> {missing_count} ta savolni "\n                "qo'lda ko'rib chiqing."\n            )\n        lines.append(\n            f"📊 Natijadorlik: {aggregate['avg_natijadorlik']} | "\n'''
replace_once(
    "handlers/admin.py",
    full_old,
    full_new,
    "partial AI analysis warning",
)
