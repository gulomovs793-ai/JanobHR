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
    "business": Plan("business", "BUSINESS", 1_190_000, 600, 10, "Ko'p yollaydigan kompaniyalar uchun"),
    "legacy": Plan("legacy", "Amaldagi tarif", 0, None, None, "Cheklanmagan"),
}
PUBLIC_PLAN_CODES = ("start", "growth", "business")


def get_plan(code: str | None) -> Plan:
    return PLANS.get(code or "trial", PLANS["trial"])


def format_som(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"
