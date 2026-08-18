"""Janob HR Bot — vakansiya tanlash bosqichi."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from handlers.questions import ask_current_question
from states import ApplyForm
from vacancies import VACANCIES

router = Router(name="vacancy")


@router.callback_query(ApplyForm.choosing_vacancy, F.data.startswith("vacancy:"))
async def choose_vacancy(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    vacancy = VACANCIES.get(key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    await state.update_data(
        vacancy_key=key,
        vacancy_title=vacancy["title"],
        question_index=0,
        answers={},
        ai_scores={},
    )
    await callback.message.edit_text(f"Siz tanladingiz: <b>{vacancy['title']}</b>")
    await ask_current_question(callback.message, state)
    await callback.answer()
