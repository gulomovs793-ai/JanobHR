"""Janob HR tariflari va limitlari uchun yagona manba."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price: int
    application_limit: int | None
    vacancy_limit: int | None
    description: str


PLANS = {
    "trial": Plan("trial", "Sinov", 0, 5, 1, "Birinchi 5 ta ariza bepul"),
    "start": Plan("start", "START", 299_000, 50, 1, "Kichik jamoalar uchun"),
    "growth": Plan("growth", "GROWTH", 599_000, 200, 3, "O'sayotgan biznes uchun"),
    "business": Plan("business", "BUSINESS", 1_000, 600, 10, "Ko'p yollaydigan kompaniyalar uchun"),
    "legacy": Plan("legacy", "Amaldagi tarif", 0, None, None, "Cheklanmagan"),
}
PUBLIC_PLAN_CODES = ("start", "growth", "business")
PLAN_LEVELS = {code: level for level, code in enumerate(PUBLIC_PLAN_CODES, 1)}


def get_plan(code: str | None) -> Plan:
    return PLANS.get(code or "trial", PLANS["trial"])


def get_plan_transition(
    current_code: str | None,
    target_code: str,
    *,
    current_expired: bool,
) -> str:
    """Return the only valid UI/backend transition for a tariff purchase.

    Paid plans may be renewed or upgraded while active. A downgrade becomes
    available only after the current paid period has expired.
    """
    if target_code not in PUBLIC_PLAN_CODES:
        raise ValueError("Noto'g'ri tarif")
    if current_code not in PUBLIC_PLAN_CODES or current_expired:
        return "select"
    current_level = PLAN_LEVELS[current_code]
    target_level = PLAN_LEVELS[target_code]
    if target_level < current_level:
        return "blocked"
    if target_level == current_level:
        return "renew"
    return "upgrade"


def format_som(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"
