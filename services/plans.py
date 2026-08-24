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
    },
    "business": {
        "key": "business",
        "name": "🔵 BUSINESS ⭐",
        "price": 449_000,
        "applications": 100,
        "vacancies": 3,
        "days": 60,
    },
    "pro": {
        "key": "pro",
        "name": "🟣 PRO",
        "price": 999_000,
        "applications": 300,
        "vacancies": 10,
        "days": 90,
    },
}

PLAN_ORDER = ["start", "business", "pro"]


def format_plan_line(plan: dict) -> str:
    return (
        f"{plan['name']}\n"
        f"  💰 {plan['price']:,} so'm | 👤 {plan['applications']} nomzod | "
        f"📋 {plan['vacancies']} vakansiya | 📅 {plan['days']} kun"
    ).replace(",", " ")
