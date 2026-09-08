"""Demo experience shown only in the public Janob HR candidate bot."""

from html import escape

from aiogram import F, Router
from aiogram.filters import BaseFilter, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, MAX_ANSWER_CHARS
from services.ai_scoring import aggregate_scores, score_answer, candidate_recommendation

router = Router(name="candidate_demo")

# Public demo uchun tasdiqlangan 6 ta SAVOL QAT'IY RO'YXAT.
# Savol matnlari o'zgartirilmaydi, AI orqali generatsiya qilinmaydi va skip qilinmaydi.
# Faqat kompetensiyani o'lchaydigan 4- va 5-savollar 0-100 AI ballga kiradi.
# 1, 2, 3 va 6-savollar fakt/filtr bo'lib, to'g'ri qisqa javob uchun ballni pasaytirmaydi.
_DEMO_QUESTIONS = [
    {
        "key": "demo_sales_experience",
        "text": "Oldin sotuv sohasida ishlaganmisiz? (Ha/Yo'q)",
        "locked": True,
        "required": True,
        "hard_filter": True,
        "ai_score": False,
    },
    {
        "key": "demo_sales_duration",
        "text": "Qayerda va qancha muddat sotuv qilgansiz? Qisqacha yozing.",
        "locked": True,
        "required": True,
        "ai_score": False,
    },
    {
        "key": "demo_crm",
        "text": "Qanday CRM tizimlarida ishlagansiz? (Bitrix24, amoCRM va h.k.)",
        "locked": True,
        "required": True,
        "ai_score": False,
    },
    {
        "key": "demo_scorecard_plan",
        "text": (
            "Bizning kompaniya keyingi chorakda sotuvni kamida $20,000 ga oshirishi kerak. "
            "Ishga kelganingizdan keyin birinchi 30 kun ichida bunga qanday hissa qo'shasiz? "
            "Aniq rejangizni 3 ta qadamda yozing."
        ),
        "locked": True,
        "required": True,
        "ai_score": True,
    },
    {
        "key": "demo_achievement",
        "text": (
            "Oldingi ish joyingizda erishgan eng katta va aniq yutug'ingizni yozing "
            "(iloji bo'lsa, raqamlar bilan)."
        ),
        "locked": True,
        "required": True,
        "ai_score": True,
    },
    {
        "key": "demo_salary",
        "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
        "locked": True,
        "required": True,
        "ai_score": False,
    },
]

_NEGATIVE_ANSWERS = {"yo'q", "yoq", "yo'q.", "yoq.", "no", "нет"}
_RED_FLAG_LABELS = {
    "qurbon_sindromi": "muvaffaqiyatsizlik sababini tashqi omillarga yuklash signali",
    "abstrakt_javob": "aniq qadam yoki dalil yetishmaydi",
    "narsissizm": "jamoaviy natijada shaxsiy hissani haddan tashqari oshirish signali",
    "ai_yozgan": "javob haddan tashqari sun'iy tayyorlangan bo'lishi mumkin",
    "natija_isbotsiz": "da'vo qilingan natija yetarli dalil bilan ochilmagan",
    "tajriba_shubhali": "amaliy tajribani qo'shimcha tekshirish kerak",
    "tez_tez_ish_almashtirish": "ish barqarorligini qo'shimcha tekshirish kerak",
    "javob_zid": "javoblarda bir-biriga zid ma'lumot bor",
}


class DemoForm(StatesGroup):
    answering = State()


class PlainMainStart(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not BOT_TOKEN or message.bot.token != BOT_TOKEN:
            return False
        parts = (message.text or "").split(maxsplit=1)
        return len(parts) == 1


def _short(value: object, limit: int = 180) -> str:
    text = str(value or "—").strip() or "—"
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return escape(text)


def _is_negative(value: object) -> bool:
    normalized = str(value or "").strip().lower().replace("’", "'").replace("ʼ", "'")
    return normalized in _NEGATIVE_ANSWERS


def _score_line(label: str, result: dict | None) -> str:
    if not isinstance(result, dict):
        return f"<b>{label}</b>\n\nAI tahlili vaqtincha mavjud emas."
    score = int(result.get("score", 0))
    izoh = _short(result.get("izoh") or "Izoh mavjud emas", 260)
    return f"<b>{label} — {score}/100</b>\n\n{izoh}"


def _interview_checks(aggregate: dict | None) -> list[str]:
    if not aggregate:
        return ["AI tahlili qayta ishlagach, kompetensiya savollarini qo'lda tekshiring."]
    checks: list[str] = []
    if aggregate.get("avg_natijadorlik", 100) < 70:
        checks.append("Oldingi natijalarini raqam, davr va shaxsiy hissasi bilan tasdiqlatish.")
    if aggregate.get("avg_masuliyat", 100) < 70:
        checks.append("Natijada aynan o'zi bajargan ishlarni jamoa hissasidan ajratib so'rash.")
    if aggregate.get("avg_aniqlik", 100) < 70:
        checks.append("$20,000 maqsad uchun aniq funnel, kunlik KPI va 30 kunlik qadamlarni ochdirish.")
    if not checks:
        checks.append("Natijalarni oldingi rahbar yoki CRM hisobotlari bilan tasdiqlash.")
    return checks[:3]


async def _ask_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    index = int(data.get("demo_index", 0))
    if index >= len(_DEMO_QUESTIONS):
        await _finish_demo(message, state)
        return
    item = _DEMO_QUESTIONS[index]
    await message.answer(
        f"<b>{index + 1}/{len(_DEMO_QUESTIONS)}</b>\n\n{item['text']}"
    )
    await state.set_state(DemoForm.answering)


async def _finish_demo(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    answers = dict(data.get("demo_answers", {}))
    ai_scores = dict(data.get("demo_ai_scores", {}))
    aggregate = aggregate_scores(ai_scores)

    experience_failed = _is_negative(answers.get("demo_sales_experience"))
    if aggregate:
        score = int(aggregate["avg_score"])
        if experience_failed:
            recommendation = "🔴 <b>Minimal tajriba filtri o'tmadi.</b>"
        else:
            recommendation = candidate_recommendation(
                ai_scores, [q["key"] for q in _DEMO_QUESTIONS if q.get("ai_score")]
            )
        score_intro = (
            "Agar siz nomzod bo'lganingizda, Janob HR sizga "
            f"<b>{score}/100</b> ball bergan bo'lardi."
        )
        metrics = (
            f"📈 Natijadorlik: <b>{aggregate['avg_natijadorlik']}</b>\n"
            f"🛠 Amaliylik: <b>{aggregate['avg_masuliyat']}</b>\n"
            f"🎯 Aniqlik: <b>{aggregate['avg_aniqlik']}</b>"
        )
    else:
        recommendation = "⚪ <b>AI tahlili vaqtincha to'liq chiqmagan.</b>"
        score_intro = "Kompetensiya savollari bo'yicha AI tahlili hozir to'liq chiqmagan."
        metrics = ""

    plan_score = ai_scores.get("demo_scorecard_plan")
    achievement_score = ai_scores.get("demo_achievement")
    valid_scores = [v for v in (plan_score, achievement_score) if isinstance(v, dict)]
    strongest = max(valid_scores, key=lambda x: x.get("score", 0), default=None)
    weakest = min(valid_scores, key=lambda x: x.get("score", 100), default=None)

    strength_text = _short(
        (strongest or {}).get("evidence")
        or (strongest or {}).get("izoh")
        or "Kuchli tomon chiqarish uchun AI tahlili yetarli emas.",
        260,
    )

    flags: list[str] = []
    if aggregate:
        for flag in aggregate.get("red_flags", []):
            label = _RED_FLAG_LABELS.get(str(flag), str(flag).replace("_", " "))
            if label not in flags:
                flags.append(label)
    if flags:
        risk_text = "; ".join(_short(x, 160) for x in flags[:2])
    elif weakest and int(weakest.get("score", 100)) < 70:
        risk_text = _short(weakest.get("izoh") or "Ayrim javoblarni aniqlashtirish kerak.", 260)
    else:
        risk_text = "Jiddiy xavf signali aniqlanmadi."

    if not aggregate:
        risk_text = "AI tahlili mavjud emas — xavfni qo‘lda tekshiring."
    if experience_failed:
        recommendation = "🔴 <b>Minimal tajriba filtri o‘tmadi.</b>"

    checks = _interview_checks(aggregate)
    checks_text = "\n".join(f"• {_short(item, 240)}" for item in checks)

    result_text = (
        "📊 <b>Demo natijangiz tayyor</b>\n\n"
        f"{score_intro}\n\n"
        "👤 <b>Nomzod profili</b>\n\n"
        f"Tajriba: {_short(answers.get('demo_sales_duration'))}\n"
        f"CRM: {_short(answers.get('demo_crm'))}\n"
        f"Kutilayotgan maosh: {_short(answers.get('demo_salary'))}\n\n"
        "🧠 <b>AI tahlili</b>\n\n"
        f"{_score_line('30 kunlik sotuv rejasi', plan_score)}\n\n"
        f"{_score_line('Oldingi yutuq', achievement_score)}"
    )
    if metrics:
        result_text += f"\n\n<b>Baholash</b>\n{metrics}"
    result_text += (
        f"\n\n✅ <b>Kuchli tomon</b>\n\n{strength_text}"
        f"\n\n⚠️ <b>Tekshirish kerak</b>\n\n{risk_text}"
        f"\n\n🏁 <b>Janob HR tavsiyasi</b>\n{recommendation}"
    )
    await message.answer(result_text)

    builder = InlineKeyboardBuilder()
    builder.button(text="🚀 HR botimni yaratish", callback_data="business:start")
    builder.button(text="Hozir emas", callback_data="business:skip")
    builder.adjust(1)
    await message.answer(
        "🏢 <b>O'zingizning HR botingizni yaratib ko'rasizmi?</b>\n\n"
        "U sizning vakansiyalaringiz, savollaringiz va talablaringiz asosida ishlaydi.",
        reply_markup=builder.as_markup(),
    )
    await state.clear()


@router.message(CommandStart(), PlainMainStart())
async def demo_start(message: Message, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ Boshlash", callback_data="demo:start")
    await message.answer(
        "👋 <b>Assalomu alaykum</b>\n\n"
        "Bu — <b>Janob HR nomzod botining qisqa demosi</b>.\n\n"
        "Tasavvur qiling, siz hozir ishga topshirayotgan nomzodsiz.\n\n"
        "Janob HR siz bilan qanday gaplashadi, qanday savol beradi va "
        "ma'lumotni qanday yig'adi — hozir o'zingiz ko'rasiz.\n\n"
        "Oxirida javoblaringiz asosida Janob HR qanday tahlil chiqarishini ham ko'rsatamiz.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "demo:start")
async def begin_demo(callback: CallbackQuery, state: FSMContext):
    if not BOT_TOKEN or callback.bot.token != BOT_TOKEN:
        await callback.answer("Bu demo faqat Janob HR asosiy botida mavjud.", show_alert=True)
        return
    await state.clear()
    await state.update_data(demo_index=0, demo_answers={}, demo_ai_scores={})
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await callback.message.answer(
        "🎭 <b>Demo boshlandi</b>\n\n"
        "💼 Vakansiya: <b>Sotuv menejeri</b>\n\n"
        "Siz hozir nomzod sifatida 6 ta savolga javob berasiz. "
        "Javoblaringizdan keyin Janob HR siz haqingizda qanday tahlil chiqarishini ko'rasiz."
    )
    await _ask_question(callback.message, state)


@router.message(DemoForm.answering, F.text)
async def demo_answer(message: Message, state: FSMContext):
    answer = (message.text or "").strip()
    if not answer:
        await message.answer("Bu savol majburiy. Javobingizni yozing.")
        return
    if len(answer) > MAX_ANSWER_CHARS:
        await message.answer("Javob juda uzun. Iltimos, qisqaroq yozing.")
        return

    data = await state.get_data()
    index = int(data.get("demo_index", 0))
    if index >= len(_DEMO_QUESTIONS):
        await _finish_demo(message, state)
        return

    item = _DEMO_QUESTIONS[index]
    answers = dict(data.get("demo_answers", {}))
    scores = dict(data.get("demo_ai_scores", {}))
    answers[item["key"]] = answer

    # Faqat baholashga mos kompetensiya savollari 0-100 score oladi.
    # Faktik savollar uchun "natijadorlik/mas'uliyat" qidirilmaydi — bu eski past ball muammosini bartaraf etadi.
    if item.get("ai_score"):
        result = await score_answer(item["text"], answer)
        if isinstance(result, dict):
            scores[item["key"]] = result

    await state.update_data(
        demo_index=index + 1,
        demo_answers=answers,
        demo_ai_scores=scores,
    )
    await _ask_question(message, state)


@router.message(DemoForm.answering)
async def demo_wrong_type(message: Message):
    await message.answer("Bu savol majburiy. Javobni matn ko'rinishida yozing.")
