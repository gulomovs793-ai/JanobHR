"""Janob HR tariflari, limitlari va feature-gate'lari uchun yagona manba."""

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
PLAN_LEVELS = {code: level for level, code in enumerate(PUBLIC_PLAN_CODES, 1)}

# Tariflar orasidagi real funksional farq. Trial START darajasidagi imkoniyatlarni
# beradi; legacy eski mijozlarni buzmaslik uchun BUSINESS darajasida qoladi.
FEATURE_AI_SCREENING = "ai_screening"
FEATURE_BASIC_INTERVIEW = "basic_interview"
FEATURE_EXCEL_EXPORT = "excel_export"
FEATURE_RISK_SIGNALS = "risk_signals"
FEATURE_TOP_CANDIDATE_COMPARE = "top_candidate_compare"
FEATURE_FUNNEL_ANALYTICS = "funnel_analytics"
FEATURE_AUTO_INTERVIEW_REMINDERS = "auto_interview_reminders"
FEATURE_PER_VACANCY_REPORTING = "per_vacancy_reporting"
FEATURE_ADVANCED_REPORTING = "advanced_reporting"
FEATURE_PRIORITY_SUPPORT = "priority_support"

FEATURE_LABELS = {
    FEATURE_AI_SCREENING: "AI saralash va nomzod baholash",
    FEATURE_BASIC_INTERVIEW: "Suhbatlarni boshqarish",
    FEATURE_EXCEL_EXPORT: "Excel eksport",
    FEATURE_RISK_SIGNALS: "Red flag va risk signallari",
    FEATURE_TOP_CANDIDATE_COMPARE: "Top nomzodlarni taqqoslash",
    FEATURE_FUNNEL_ANALYTICS: "Hiring funnel analytics",
    FEATURE_AUTO_INTERVIEW_REMINDERS: "Avtomatik suhbat eslatmalari",
    FEATURE_PER_VACANCY_REPORTING: "Vakansiya bo'yicha hisobot",
    FEATURE_ADVANCED_REPORTING: "Kengaytirilgan conversion hisobotlari",
    FEATURE_PRIORITY_SUPPORT: "Priority support",
}

_BASE_FEATURES = frozenset(
    {
        FEATURE_AI_SCREENING,
        FEATURE_BASIC_INTERVIEW,
        FEATURE_EXCEL_EXPORT,
    }
)
_GROWTH_FEATURES = _BASE_FEATURES | {
    FEATURE_RISK_SIGNALS,
    FEATURE_TOP_CANDIDATE_COMPARE,
    FEATURE_FUNNEL_ANALYTICS,
    FEATURE_AUTO_INTERVIEW_REMINDERS,
    FEATURE_PER_VACANCY_REPORTING,
}
_BUSINESS_FEATURES = _GROWTH_FEATURES | {
    FEATURE_ADVANCED_REPORTING,
    FEATURE_PRIORITY_SUPPORT,
}
_PLAN_FEATURES = {
    "trial": _BASE_FEATURES,
    "start": _BASE_FEATURES,
    "growth": _GROWTH_FEATURES,
    "business": _BUSINESS_FEATURES,
    "legacy": _BUSINESS_FEATURES,
}

_FEATURE_MIN_PLAN = {
    FEATURE_AI_SCREENING: "start",
    FEATURE_BASIC_INTERVIEW: "start",
    FEATURE_EXCEL_EXPORT: "start",
    FEATURE_RISK_SIGNALS: "growth",
    FEATURE_TOP_CANDIDATE_COMPARE: "growth",
    FEATURE_FUNNEL_ANALYTICS: "growth",
    FEATURE_AUTO_INTERVIEW_REMINDERS: "growth",
    FEATURE_PER_VACANCY_REPORTING: "growth",
    FEATURE_ADVANCED_REPORTING: "business",
    FEATURE_PRIORITY_SUPPORT: "business",
}

# Billing kartasida foydalanuvchiga ko'rsatiladigan, texnik bo'lmagan qisqa ro'yxat.
_MARKET_FEATURES = {
    "start": (
        FEATURE_AI_SCREENING,
        FEATURE_BASIC_INTERVIEW,
        FEATURE_EXCEL_EXPORT,
    ),
    "growth": (
        FEATURE_AI_SCREENING,
        FEATURE_BASIC_INTERVIEW,
        FEATURE_EXCEL_EXPORT,
        FEATURE_RISK_SIGNALS,
        FEATURE_TOP_CANDIDATE_COMPARE,
        FEATURE_AUTO_INTERVIEW_REMINDERS,
        FEATURE_FUNNEL_ANALYTICS,
    ),
    "business": (
        FEATURE_AI_SCREENING,
        FEATURE_RISK_SIGNALS,
        FEATURE_TOP_CANDIDATE_COMPARE,
        FEATURE_AUTO_INTERVIEW_REMINDERS,
        FEATURE_FUNNEL_ANALYTICS,
        FEATURE_ADVANCED_REPORTING,
        FEATURE_PRIORITY_SUPPORT,
    ),
}


def get_plan(code: str | None) -> Plan:
    return PLANS.get(code or "trial", PLANS["trial"])


def plan_features(code: str | None) -> frozenset[str]:
    return _PLAN_FEATURES.get(code or "trial", _PLAN_FEATURES["trial"])


def has_feature(code: str | None, feature: str) -> bool:
    return feature in plan_features(code)


def minimum_plan_for_feature(feature: str) -> str:
    return _FEATURE_MIN_PLAN.get(feature, "business")


def feature_label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature.replace("_", " ").capitalize())


def market_feature_labels(code: str) -> list[str]:
    features = _MARKET_FEATURES.get(code, ())
    return [feature_label(feature) for feature in features]


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
