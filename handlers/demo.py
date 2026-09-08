"""Demo experience shown only in the public Janob HR candidate bot."""

from aiogram import F, Router
from aiogram.filters import BaseFilter, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN, MAX_ANSWER_CHARS
from handlers.admin import format_candidate_card
from services.ai_scoring import aggregate_scores, score_answer

router = Router(name="candidate_demo")

_DEMO_QUESTIONS = [
    {
        "key": "demo_achievement",
        "text": "Oldingi ish joyingizda erishgan eng yaxshi natijangizni ayting. Iloji bo'lsa, raqam bilan yozing.",
    },
    {
        "key": "demo_client",
        "text": "Qiyin mijoz yoki muammoli vaziyatni qanday hal qilgansiz? Bitta real misol keltiring.",
    },
    {
        "key": "demo_mistake",
        "text": "Ishda qilgan bir xatoyingiz va undan olgan sabog'ingizni ayting.",
    },
    {
        "key": "demo_plan",
        "text": "Yangi ishga kirsangiz, birinchi 30 kunni qanday rejalashtirasiz? Aniq qadamlar bilan yozing.",
    },
]


class DemoForm(StatesGroup):
    answering = State()


class PlainMainStart(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not BOT_TOKEN or message.bot.token != BOT_TOKEN:
            return False
        parts = (message.text or "").split(maxsplit=1)
        return len(parts) == 1


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
    ai_scores = data.get("demo_ai_scores", {})
    aggregate = aggregate_scores(ai_scores)

    if aggregate:
        score_intro = (
            "Agar siz nomzod bo'lganingizda, Janob HR sizga "
            f"<b>{aggregate['avg_score']}/100</b> ball bergan bo'lardi."
        )
        metrics = (
            f"📈 Natijadorlik: <b>{aggregate['avg_natijadorlik']}</b>\n"
            f"🧭 Mas'uliyat: <b>{aggregate['avg_masuliyat']}</b>\n"
            f"🎯 Aniqlik: <b>{aggregate['avg_aniqlik']}</b>"
        )
    else:
        score_intro = (
            "AI tahlili hozir to'liq chiqmagan bo'lsa ham, Janob HR "
            "javoblarni admin uchun shu ko'rinishda jamlaydi."
        )
        metrics = ""

    preview = format_candidate_card(
        {
            "full_name": message.from_user.full_name,
            "vacancy_title": "Sotuv menejeri · demo",
            "phone_number": "—",
            "ai_scores": ai_scores,
        },
        show_risks=True,
    )

    result_text = (
        "📊 <b>Demo natijangiz tayyor</b>\n\n"
        f"{score_intro}"
    )
    if metrics:
        result_text += f"\n\n{metrics}"
    result_text += (
        "\n\n<b>Admin botga yuboriladigan qisqa tahlil:</b>\n\n"
        f"{preview}\n\n"
        "Janob HR nomzodlarning javoblarini yig'adi, tahlil qiladi va "
        "ish beruvchiga tayyor natija qilib beradi."
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
    builder.button(text="Boshlash", callback_data="demo:start")
    await message.answer(
        "👋 <b>Assalomu alaykum</b>\n\n"
        "Tasavvur qiling, siz hozir ishga topshirayotgan nomzodsiz.\n\n"
        "Janob HR siz bilan qanday gaplashadi, qanday savol beradi va "
        "ma'lumotni qanday yig'adi — hozir o'zingiz ko'rasiz.",
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
        "🎭 <b>Demo boshlandi.</b> Siz hozir Sotuv menejeri lavozimiga nomzodsiz."
    )
    await _ask_question(callback.message, state)


@router.message(DemoForm.answering, F.text)
async def demo_answer(message: Message, state: FSMContext):
    answer = (message.text or "").strip()
    if not answer:
        await message.answer("Javobingizni qisqacha yozing.")
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
    await message.answer("Bu demoda javobni matn ko'rinishida yozing.")
