"""Janob HR — pullik tarif rejalari (5 ta bepul ariza sinovidan keyin).

Sinov paytida (`tenant.status == "trial"`) BARCHA funksiya ochiq — tarif
cheklovi qo'llanilmaydi. Sinov tugagach, mijoz shu 3 tarifdan birini tanlaydi.
"""

# Har bir tarifda REAL, kodda tekshiriladigan funksiyalar (tenant_has_feature
# orqali). "start" hech qaysi qo'shimcha funksiyaga ega emas — bo'sh to'plam.
_FEATURES_BY_PLAN = {
    "start": set(),
    "business": {"voice", "interview_scheduling", "advanced_stats", "resume_autofill"},
    "pro": {"voice", "interview_scheduling", "advanced_stats", "resume_autofill"},
}

PLANS = {
    "start": {
        "key": "start",
        "name": "🟢 START",
        "price": 199_000,
        "applications": 30,
        "vacancies": 1,
        "days": 30,
        "features": [
            "AI orqali ariza baholash (filtr + chuqur tahlil)",
            "AI savollarni avtomatik generatsiya qilish",
            "Excel eksport",
            "Asosiy statistika",
        ],
    },
    "business": {
        "key": "business",
        "name": "🔵 BUSINESS ⭐",
        "price": 449_000,
        "applications": 100,
        "vacancies": 3,
        "days": 60,
        "features": [
            "START'dagi barchasi, plyus:",
            "🎙 Majburiy ovozli savol",
            "📅 Suhbat vaqtlarini avtomatik boshqarish",
            "📊 Kuchaytirilgan statistika (trend, sifat taqsimoti)",
            "📄 Rezyumedan avtomatik to'ldirish",
        ],
    },
    "pro": {
        "key": "pro",
        "name": "🟣 PRO",
        "price": 999_000,
        "applications": 300,
        "vacancies": 10,
        "days": 90,
        "features": [
            "BUSINESS'dagi barchasi, plyus:",
            "⚡ Ustuvor qo'llab-quvvatlash",
        ],
    },
}

PLAN_ORDER = ["start", "business", "pro"]


def tenant_has_feature(tenant: dict | None, feature: str) -> bool:
    """Sinov paytida HAMMASI ochiq. Sinovdan keyin — faqat tanlagan tarifida
    bor funksiyalar. Real (kodda ta'sir qiladigan) funksiyalar: "voice",
    "interview_scheduling", "advanced_stats", "resume_autofill"."""
    if not tenant:
        return False
    if tenant.get("status") == "trial":
        return True
    return feature in _FEATURES_BY_PLAN.get(tenant.get("plan"), set())


def format_plan_line(plan: dict) -> str:
    return (
        f"{plan['name']}\n"
        f"  💰 {plan['price']:,} so'm | 👤 {plan['applications']} nomzod | "
        f"📋 {plan['vacancies']} vakansiya | 📅 {plan['days']} kun"
    ).replace(",", " ")


def format_plan_detail(plan: dict) -> str:
    features = "\n".join(f"• {f}" for f in plan["features"])
    price = f"{plan['price']:,}".replace(",", " ")
    return (
        f"{plan['name']}\n\n"
        f"💰 Narxi: {price} so'm\n"
        f"👤 {plan['applications']} ta nomzod\n"
        f"📋 {plan['vacancies']} ta vakansiya\n"
        f"📅 {plan['days']} kun amal qiladi\n\n"
        f"<b>Nimalar kiradi:</b>\n{features}"
    )
