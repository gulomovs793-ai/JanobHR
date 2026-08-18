"""Janob HR Bot — savol-javob oqimi, hard-filter va AI baholash."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from services import database
from services.ai_scoring import score_answer
from states import ApplyForm
from vacancies import VACANCIES, is_negative_answer

logger = logging.getLogger("janob_hr_bot")

router = Router(name="questions")


async def ask_current_question(message: Message, state: FSMContext):
    data = await state.get_data()
    vacancy_key = data["vacancy_key"]
    idx = data["question_index"]
    questions = VACANCIES[vacancy_key]["questions"]

    if idx >= len(questions):
        await finish_questions(message, state)
        return

    await message.answer(questions[idx]["text"])
    await state.set_state(ApplyForm.answering_questions)


@router.message(ApplyForm.answering_questions, F.text)
async def handle_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    vacancy_key = data["vacancy_key"]
    idx = data["question_index"]
    questions = VACANCIES[vacancy_key]["questions"]
    q = questions[idx]
    answer_text = message.text.strip()

    # --- Hard filter: salbiy javob bo'lsa, darhol xushmuomalalik bilan rad etamiz ---
    if q.get("hard_filter") and is_negative_answer(answer_text):
        vacancy = VACANCIES[vacancy_key]
        await message.answer(vacancy["reject_message"])

        answers = data.get("answers", {})
        answers[q["key"]] = answer_text
        await database.save_application(
            user_id=message.from_user.id,
            username=message.from_user.username or "",
            full_name=message.from_user.full_name,
            vacancy_key=vacancy_key,
            vacancy_title=vacancy["title"],
            answers=answers,
            ai_scores=data.get("ai_scores", {}),
            resume_file_id=None,
            video_file_id=None,
            status="rejected_hard_filter",
        )
        await state.clear()
        return

    answers = data.get("answers", {})
    answers[q["key"]] = answer_text

    ai_scores = data.get("ai_scores", {})
    if q.get("ai_score"):
        score = await score_answer(q["text"], answer_text)
        if score is not None:
            ai_scores[q["key"]] = score

    await state.update_data(answers=answers, ai_scores=ai_scores, question_index=idx + 1)
    await ask_current_question(message, state)


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
