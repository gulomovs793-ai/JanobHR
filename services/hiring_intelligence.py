"""Janob HR 2.0 — nomzodlarni taqqoslash, risk signallari va hiring funnel.

Bu qatlam qaror QABUL QILMAYDI. U admin uchun tushunarli signal va dalil beradi.
Red flag hech qachon o'zi avtomatik rad sababi bo'lmasligi kerak.
"""

from __future__ import annotations

import re
from typing import Any

from services.ai_scoring import aggregate_scores

_TERMINAL_AUTO_REJECT = {
    "rejected_hard_filter",
    "rejected_irrelevant",
    "rejected_ai_generated",
}
_INTERVIEW_REACHED = {"accepted", "hired", "not_hired", "no_show"}
_ACTIVE_COMPARE = {"pending", "saved", "accepted"}

_RISK_LABELS = {
    "qurbon_sindromi": "Mas'uliyatni tashqi omillarga yuklash signali",
    "abstrakt_javob": "Javobda aniq misol yoki o'lchov yetishmaydi",
    "narsissizm": "Jamoa natijasini faqat o'ziniki sifatida ko'rsatish signali",
    "ai_yozgan": "Javob AI yordamida tayyorlangan bo'lishi mumkin",
    "natija_isbotsiz": "Da'vo aniq dalil yoki raqam bilan tasdiqlanmagan",
    "tajriba_shubhali": "Amaliy tajriba bo'yicha aniqlashtirish kerak",
    "tez_tez_ish_almashtirish": "Ish joylarini tez-tez almashtirish signali",
    "javob_zid": "Javob ichida bir-biriga zid ma'lumot bor",
    "maosh_budgetdan_yuqori": "Kutilayotgan maosh vakansiya budjetidan yuqori",
    "past_moslik": "Umumiy moslik bahosi past",
}


def _normalise_number(raw: str) -> float | None:
    raw = raw.strip().replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def extract_salary_expectation(answers: dict[str, Any]) -> dict | None:
    """Javoblardan taxminiy maoshni chiqaradi.

    UZS uchun `8 mln`, `8 million`, `8000000`, `$700` kabi odatiy formatlarni
    tushunadi. Valyuta aniqlanmasa UZS deb hisoblaydi, chunki asosiy bozor O'zbekiston.
    """
    candidates: list[str] = []
    for key, value in (answers or {}).items():
        key_l = str(key).lower()
        text = str(value or "").strip()
        if not text:
            continue
        if any(token in key_l for token in ("salary", "maosh", "oylik", "kutilayotgan")):
            candidates.insert(0, text)
        elif re.search(r"\b(?:mln|million|so['’]?m|uzs|usd|dollar|\$)\b", text.lower()):
            candidates.append(text)

    for text in candidates:
        lower = text.lower()
        currency = "USD" if "$" in text or "usd" in lower or "dollar" in lower else "UZS"
        match = re.search(r"(\d+(?:[\s.,]\d+)?)", lower)
        if not match:
            continue
        number = _normalise_number(match.group(1))
        if number is None:
            continue
        if currency == "UZS" and ("mln" in lower or "million" in lower):
            number *= 1_000_000
        elif currency == "UZS" and number < 100_000 and re.search(r"\bming\b", lower):
            number *= 1_000
        return {"amount": round(number), "currency": currency, "raw": text[:120]}
    return None


def candidate_risks(app: dict, vacancy: dict | None = None) -> list[dict]:
    """AI bayroqlari + biznes qoidalaridan tushunarli risk signallarini qaytaradi."""
    codes: list[str] = []
    aggregate = aggregate_scores(app.get("ai_scores") or {})
    if aggregate:
        codes.extend(aggregate.get("red_flags") or [])
        if aggregate.get("avg_score", 100) < 50:
            codes.append("past_moslik")
    if app.get("ai_suspect_flags") and "ai_yozgan" not in codes:
        codes.append("ai_yozgan")

    salary = extract_salary_expectation(app.get("answers") or {})
    profile = (vacancy or {}).get("profile") or {}
    budget = profile.get("salary_budget_max")
    try:
        budget = int(budget) if budget not in (None, "") else None
    except (TypeError, ValueError):
        budget = None
    if salary and budget and salary["currency"] == "UZS" and salary["amount"] > budget:
        codes.append("maosh_budgetdan_yuqori")

    result = []
    seen = set()
    for code in codes:
        code = str(code)
        if code in seen:
            continue
        seen.add(code)
        severity = "high" if code in {"qurbon_sindromi", "tajriba_shubhali", "maosh_budgetdan_yuqori", "past_moslik"} else "medium"
        result.append(
            {
                "code": code,
                "label": _RISK_LABELS.get(code, code.replace("_", " ").capitalize()),
                "severity": severity,
            }
        )
    return result


def candidate_strength(app: dict) -> dict:
    scores = [
        value
        for value in (app.get("ai_scores") or {}).values()
        if isinstance(value, dict) and isinstance(value.get("score"), (int, float))
    ]
    aggregate = aggregate_scores(app.get("ai_scores") or {})
    strongest = max(scores, key=lambda value: value.get("score", 0), default={})
    evidence = str(strongest.get("evidence") or strongest.get("dalil") or "").strip()
    note = str(strongest.get("izoh") or "").strip()

    dimension = "Javob sifati"
    dimension_score = aggregate.get("avg_score") if aggregate else None
    if aggregate:
        dimensions = [
            ("Natijadorlik", aggregate.get("avg_natijadorlik", 0)),
            ("Mas'uliyat", aggregate.get("avg_masuliyat", 0)),
            ("Aniqlik", aggregate.get("avg_aniqlik", 0)),
        ]
        dimension, dimension_score = max(dimensions, key=lambda item: item[1])

    summary = evidence or note or f"{dimension} bo'yicha javoblari nisbatan kuchli."
    return {
        "dimension": dimension,
        "dimension_score": dimension_score,
        "summary": summary[:240],
        "evidence": evidence[:240],
    }


def compare_candidates(apps: list[dict], vacancy: dict | None = None, limit: int = 3) -> dict:
    eligible = [app for app in apps if app.get("status") in _ACTIVE_COMPARE]

    def sort_key(app: dict):
        aggregate = aggregate_scores(app.get("ai_scores") or {})
        return (
            aggregate.get("avg_score", -1) if aggregate else -1,
            app.get("created_at") or "",
        )

    ranked = sorted(eligible, key=sort_key, reverse=True)[: max(1, min(limit, 5))]
    items = []
    for rank, app in enumerate(ranked, 1):
        aggregate = aggregate_scores(app.get("ai_scores") or {})
        strength = candidate_strength(app)
        risks = candidate_risks(app, vacancy)
        items.append(
            {
                "rank": rank,
                "id": app["id"],
                "full_name": app.get("full_name") or "—",
                "status": app.get("status"),
                "score": aggregate.get("avg_score") if aggregate else None,
                "metrics": {
                    "natijadorlik": aggregate.get("avg_natijadorlik") if aggregate else None,
                    "masuliyat": aggregate.get("avg_masuliyat") if aggregate else None,
                    "aniqlik": aggregate.get("avg_aniqlik") if aggregate else None,
                },
                "strength": strength,
                "salary": extract_salary_expectation(app.get("answers") or {}),
                "risks": risks,
            }
        )

    recommendation = None
    if items:
        top = items[0]
        reason = top["strength"]["summary"]
        recommendation = {
            "candidate_id": top["id"],
            "text": f"{top['full_name']} hozircha eng yuqori moslikka ega. {reason}",
        }
    return {"items": items, "recommendation": recommendation, "eligible": len(eligible)}


def hiring_funnel(apps: list[dict]) -> dict:
    total = len(apps)
    passed = [app for app in apps if app.get("status") not in _TERMINAL_AUTO_REJECT]
    strong = []
    for app in passed:
        aggregate = aggregate_scores(app.get("ai_scores") or {})
        if aggregate and aggregate.get("avg_score", 0) >= 75:
            strong.append(app)
    interviews = [app for app in apps if app.get("status") in _INTERVIEW_REACHED]
    hired = [app for app in apps if app.get("status") == "hired"]
    no_show = [app for app in apps if app.get("status") == "no_show"]

    def rate(value: int, base: int) -> int:
        return round(100 * value / base) if base else 0

    return {
        "applications": total,
        "passed_filter": len(passed),
        "strong": len(strong),
        "interview": len(interviews),
        "hired": len(hired),
        "no_show": len(no_show),
        "rates": {
            "filter_pass": rate(len(passed), total),
            "strong": rate(len(strong), len(passed)),
            "interview": rate(len(interviews), len(passed)),
            "hire": rate(len(hired), len(interviews)),
        },
    }
