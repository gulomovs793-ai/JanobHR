"""Janob HR Bot — savol-javob oqimi, hard-filter, mavzuga aloqadorlik va AI baholash."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from services import database
from services.ai_scoring import check_relevance, score_answer
from states import ApplyForm
from vacancies import VACANCIES, get_questions, is_negative_answer

logger = logging.getLogger("janob_hr_bot")

router = Router(name="questions")


async def ask_current_question(message: Message, state: FSMContext):
    data = await state.get_data()
    vacancy_key = data["vacancy_key"]
    idx = data["question_index"]
    questions = get_questions(vacancy_key)

    if idx >= len(questions):
        await finish_questions(message, state)
        return

    total = len(questions)
    await message.answer(f"<b>Savol {idx + 1}/{total}</b>\n\n{questions[idx]['text']}")
    await state.set_state(ApplyForm.answering_questions)


async def _reject_and_save(
    message: Message,
    state: FSMContext,
    vacancy_key: str,
    answers: dict,
    ai_scores: dict,
    reject_text: str,
    status: str,
):
    """Nomzodni xushmuomalalik bilan rad etadi, arizani baribir bazaga yozadi (statistika
    uchun) va suhbat holatini tozalaydi."""
    vacancy = VACANCIES[vacancy_key]
    await message.answer(reject_text)
    await database.save_application(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        vacancy_key=vacancy_key,
        vacancy_title=vacancy["title"],
        answers=answers,
        ai_scores=ai_scores,
        resume_file_id=None,
        video_file_id=None,
        status=status,
    )
    await state.clear()


_IRRELEVANT_REJECT_TEXT = (
    "Kechirasiz, javobingiz savolga mos kelmadi. ⚠️\n\n"
    "Iltimos, savollarga jiddiy va mavzuga oid javob bering. Agar tasodifiy xato bo'lgan "
    "bo'lsa, /start orqali qaytadan urinib ko'rishingiz mumkin."
)


@router.message(ApplyForm.answering_questions, F.text)
async def handle_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    vacancy_key = data["vacancy_key"]
    idx = data["question_index"]
    questions = get_questions(vacancy_key)
    q = questions[idx]
    answer_text = message.text.strip()

    if not answer_text:
        await message.answer("Iltimos, savolga matn ko'rinishida javob yozing.")
        return

    # --- Hard filter: salbiy javob bo'lsa, darhol xushmuomalalik bilan rad etamiz ---
    if q.get("hard_filter") and is_negative_answer(answer_text):
        answers = data.get("answers", {})
        answers[q["key"]] = answer_text
        vacancy = VACANCIES[vacancy_key]
        await _reject_and_save(
            message, state, vacancy_key, answers, data.get("ai_scores", {}),
            vacancy["reject_message"], "rejected_hard_filter",
        )
        return

    answers = data.get("answers", {})
    answers[q["key"]] = answer_text
    ai_scores = data.get("ai_scores", {})

    # --- Har bir javob uchun: mavzuga/kasbga aloqadormi degan tekshiruv ---
    if q.get("ai_score"):
        result = await score_answer(q["text"], answer_text)
        if result is not None:
            ai_scores[q["key"]] = result
            if not result.get("relevant", True):
                await _reject_and_save(
                    message, state, vacancy_key, answers, ai_scores,
                    _IRRELEVANT_REJECT_TEXT, "rejected_irrelevant",
                )
                return
    else:
        relevant = await check_relevance(q["text"], answer_text)
        if relevant is False:
            await _reject_and_save(
                message, state, vacancy_key, answers, ai_scores,
                _IRRELEVANT_REJECT_TEXT, "rejected_irrelevant",
            )
            return

    await state.update_data(answers=answers, ai_scores=ai_scores, question_index=idx + 1)
    await ask_current_question(message, state)


@router.message(ApplyForm.answering_questions)
async def handle_wrong_answer_type(message: Message):
    """Savol kutilayotganda matndan boshqa narsa (rasm, stiker va h.k.) yuborilsa."""
    await message.answer("Iltimos, javobingizni oddiy matn ko'rinishida yozing. ✍️")


async def finish_questions(message: Message, state: FSMContext):
    data = await state.get_data()
    vacancy = VACANCIES[data["vacancy_key"]]

    if vacancy.get("resume_required"):
        await message.answer(
            "Rahmat! Endi, iltimos, rezyumeingizni (PDF fayl) yoki qisqa video-vizitkangizni yuboring."
        )
        await state.set_state(ApplyForm.waiting_file)
        return

    await complete_application(message, state)


async def complete_application(
    message: Message,
    state: FSMContext,
    resume_file_id: str | None = None,
    video_file_id: str | None = None,
):
    from handlers.admin import notify_admin_group
    from handlers.sell import maybe_send_sell_pitch

    data = await state.get_data()
    vacancy = VACANCIES[data["vacancy_key"]]

    app_id = await database.save_application(
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        vacancy_key=data["vacancy_key"],
        vacancy_title=vacancy["title"],
        answers=data.get("answers", {}),
        ai_scores=data.get("ai_scores", {}),
        resume_file_id=resume_file_id,
        video_file_id=video_file_id,
        status="pending",
    )

    await message.answer("✅ Anketangiz qabul qilindi! Tez orada siz bilan bog'lanamiz. Rahmat!")
    await state.set_state(ApplyForm.finished)
    await state.clear()

    try:
        await notify_admin_group(message.bot, app_id)
    except Exception:
        logger.exception("Admin guruhga xabar yuborib bo'lmadi (app_id=%s).", app_id)

    # --- Sell bosqichi: agar nomzod yuqori ball olsa, avtomatik taklif yuboriladi ---
    try:
        await maybe_send_sell_pitch(message, app_id, data.get("ai_scores", {}))
    except Exception:
        logger.exception("Sell xabarini yuborib bo'lmadi (app_id=%s).", app_id)
