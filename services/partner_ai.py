"""AI diagnosis for Janob HR partner onboarding.

Uses the same configured AI provider chain as candidate scoring so the partner bot
gets the same DeepSeek/OpenAI-compatible provider behavior and fallbacks.
"""

import html
import logging

from services.ai_scoring import _call_ai

logger = logging.getLogger("janob_hr_partner_ai")

ROLE_NAMES = {
    "targetolog": "Targetolog",
    "smm": "SMM manager",
    "agency": "Agentlik",
    "blogger": "Blogger",
    "other": "Boshqa",
}

_SYSTEM_PROMPT = """Sen Janob HR hamkorlik dasturidagi sotuv diagnostika yordamchisisan.
Foydalanuvchi bir nechta qisqa savolga javob berdi. Uning kasbi va javoblariga qarab unga
Janob HR nima uchun kerakligini juda sodda, odamiy va tushunarli o'zbek tilida ayt.

USLUB:
- Rasmiy korporativ til ishlatma.
- "monetizatsiya", "segment", "yechim portfeli", "daromad kanali", "onboarding" kabi og'ir so'zlarni ishlatma.
- Odamga Telegramda tanishi gapirgandek yoz.
- Avval uning holatini 1-2 gapda aynan javoblariga bog'lab ayt.
- Keyin u hozir qayerda pul/imkoniyatni qo'ldan chiqarayotganini oddiy qilib tushuntir.
- Keyin Janob HR qanday yordam berishini 2-3 gapda ayt.
- Janob HR: biznesga xodim topishda nomzodlarni qabul qiladi, savollar beradi, AI bilan saralaydi va kuchli nomzodlarni ajratadi.
- Hamkor mahsulotni tavsiya qiladi; ichki operatsion jarayonlarni tushuntirish shart emas.
- Tasdiqlangan hamkorga 2 xil yo'l beriladi: referral link va o'zi sozlaydigan promo kod.
- Referral link orqali kelgan mijoz hamkorga avtomatik biriktiriladi.
- Promo kod mijozga foiz yoki aniq summa ko'rinishida chegirma beradi, chegirma hamkorning komissiyasidan ayriladi.
- Misol: 30 000 UZS chegirma berilsa, START hamkor komissiyasi 99 000 - 30 000 = 69 000 UZS bo'ladi.
- Mijoz haqiqiy tarif sotib olsa hamkorga komissiya hisoblanadi: START 99 000 UZS, GROWTH 199 000 UZS, BUSINESS 299 000 UZS.
- Hech qachon ichki botlar, qaysi bot qayerga yo'naltirishi, Founder/Admin rollari, server, webhook, token, Render yoki boshqa texnik arxitektura haqida foydalanuvchiga aytma.
- Kompaniyaning ichki operatsiyasi, kim arizani ko'rishi yoki notification qayerga borishi haqida aytma.
- Hech qachon kafolatlangan daromad va'da qilma.
- Agar odamda hozir mijoz/auditoriya deyarli bo'lmasa, yolg'on maqtama. Hozircha imkoniyati kamligini yumshoq ayt va referral link/tayyor matnlar bilan boshlash mumkinligini tushuntir.
- Agar oxirgi javobi "hozircha yo'q" bo'lsa, bosim qilma; faqat nima berishimizni qisqa tushuntir.
- 90-130 so'zdan oshma.
- Markdown ishlatma. HTML teg yozma. Faqat tayyor matn qaytar.
"""


def _human_answers(data: dict) -> str:
    role = data.get("role", "other")
    q1 = data.get("q1")
    q2 = data.get("q2")
    q3 = data.get("q3")
    q4 = data.get("q4")

    if role in {"targetolog", "smm"}:
        return (
            f"Kasb: {ROLE_NAMES[role]}\n"
            f"Hozir ishlayotgan kompaniyalar: {q1}\n"
            f"Mijozlari xodim qidirishi: {q2}\n"
            f"Qo'shimcha daromadga qiziqishi: {q3}"
        )
    if role == "agency":
        return (
            f"Kasb: Agentlik\n"
            f"Biznes mijozlari soni: {q1}\n"
            f"Marketingdan tashqari HR muammolarini ham hal qiladimi: {q2}\n"
            f"Qo'shimcha daromadga qiziqishi: {q3}"
        )
    if role == "blogger":
        return (
            "Kasb: Blogger\n"
            f"Auditoriya turi: {q1}\n"
            f"Auditoriyada biznes egalari: {q2}\n"
            f"Blogdan hozirgi daromad turi: {q3}\n"
            f"Qo'shimcha daromadga qiziqishi: {q4}"
        )
    return (
        "Kasb: Boshqa\n"
        f"Biznes egalari bilan aloqasi: {q1}\n"
        f"Ijtimoiy tarmoq auditoriyasi: {q2}\n"
        f"Qo'shimcha daromadga qiziqishi: {q3}"
    )


async def generate_partner_advice(data: dict) -> str | None:
    """Return natural personalized advice; None if all configured AI providers fail."""
    try:
        answer = await _call_ai(
            _SYSTEM_PROMPT,
            "Foydalanuvchi javoblari:\n" + _human_answers(data),
            max_tokens=360,
        )
    except Exception:
        logger.exception("Partner AI diagnosis failed")
        return None
    if not answer:
        return None
    # Bot uses HTML parse mode; AI output is plain text, so escape accidental markup.
    return html.escape(answer.strip())[:3500]
