"""Janob HR — pullik tarif rejalari (5 ta bepul ariza sinovidan keyin).

Sinov paytida (`tenant.status == "trial"`) BARCHA funksiya ochiq — tarif
cheklovi qo'llanilmaydi. Sinov tugagach, mijoz shu 3 tarifdan birini tanlaydi.
"""

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
            "👥 Bir nechta admin (jamoa a'zolari)",
            "⚡ Ustuvor qo'llab-quvvatlash",
        ],
    },
}

PLAN_ORDER = ["start", "business", "pro"]


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
