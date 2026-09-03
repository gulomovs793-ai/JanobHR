from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    price: int
    application_limit: int
    vacancy_limit: int
    days: int
    features: tuple[str, ...]


PLANS = {
    "start": Plan(
        code="start",
        name="START",
        price=199_000,
        application_limit=50,
        vacancy_limit=1,
        days=30,
        features=(
            "50 ta nomzod arizasi",
            "1 ta faol vakansiya",
            "AI asosida nomzodlarni baholash",
            "Nomzodlar ro'yxati va statuslar",
            "Excel eksport",
        ),
    ),
    "business": Plan(
        code="business",
        name="BUSINESS",
        price=449_000,
        application_limit=150,
        vacancy_limit=3,
        days=30,
        features=(
            "150 ta nomzod arizasi",
            "3 ta faol vakansiya",
            "AI asosida nomzodlarni baholash",
            "Nomzodlar ro'yxati va statuslar",
            "Excel eksport",
            "Suhbat vaqtlarini boshqarish",
        ),
    ),
    "pro": Plan(
        code="pro",
        name="PRO",
        price=1_000,
        application_limit=500,
        vacancy_limit=10,
        days=30,
        features=(
            "500 ta nomzod arizasi",
            "10 ta faol vakansiya",
            "AI asosida nomzodlarni baholash",
            "Nomzodlar ro'yxati va statuslar",
            "Excel eksport",
            "Suhbat vaqtlarini boshqarish",
            "Prioritet qo'llab-quvvatlash",
        ),
    ),
}

DEFAULT_PLAN_CODE = "start"


def get_plan(code: str | None) -> Plan:
    return PLANS.get((code or "").lower(), PLANS[DEFAULT_PLAN_CODE])


def get_plan_transition(current_code: str | None, new_code: str | None, *, current_expired: bool) -> str:
    if current_expired:
        return "replace"
    order = {"start": 0, "business": 1, "pro": 2}
    current = order.get((current_code or DEFAULT_PLAN_CODE).lower(), 0)
    new = order.get((new_code or DEFAULT_PLAN_CODE).lower(), 0)
    if new < current:
        return "blocked"
    if new == current:
        return "extend"
    return "upgrade"


def format_som(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


def format_plan_detail(plan: Plan) -> str:
    features = "\n".join(f"• {feature}" for feature in plan.features)
    return (
        f"<b>{plan.name}</b>\n\n"
        f"{features}\n\n"
        f"Nomzodlar: <b>{plan.application_limit} ta</b>\n"
        f"Vakansiyalar: <b>{plan.vacancy_limit} ta</b>\n"
        f"Muddat: <b>{plan.days} kun</b>\n"
        f"Narx: <b>{format_som(plan.price)}</b>"
    )
