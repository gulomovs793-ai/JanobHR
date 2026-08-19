"""Janob HR Bot — vakansiya tanlash bosqichi."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from handlers.questions import ask_current_question
from services import database
from states import ApplyForm
from vacancies import build_questions

router = Router(name="vacancy")


@router.callback_query(ApplyForm.choosing_vacancy, F.data.startswith("vacancy:"))
async def choose_vacancy(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(key)
    if not vacancy or not vacancy["active"]:
        await callback.answer("Bu vakansiya endi mavjud emas.", show_alert=True)
        return

    # Vakansiyaning to'liq "suratini" (savollar, rad etish xabari va h.k.) shu
    # yerda FSM holatiga saqlab qo'yamiz — shunda keyingi har bir savolda
    # qayta-qayta bazaga murojaat qilishning hojati yo'q, va agar admin shu
    # oraliqda vakansiyani tahrirlasa ham, nomzod boshlagan versiyasi bilan
    # izchil davom etadi.
    await state.update_data(
        vacancy_key=key,
        vacancy_title=vacancy["title"],
        vacancy_reject_message=vacancy["reject_message"],
        vacancy_resume_required=vacancy["resume_required"],
        vacancy_questions=build_questions(vacancy),
        question_index=0,
        answers={},
        ai_scores={},
        irrelevant_retry_count=0,
    )
    await callback.message.edit_text(f"Siz tanladingiz: <b>{vacancy['title']}</b>")
    await ask_current_question(callback.message, state)
    await callback.answer()
