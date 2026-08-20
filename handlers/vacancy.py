"""Janob HR Bot — vakansiya tanlash bosqichi."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from i18n import DEFAULT_LANG, t
from services import database
from states import ApplyForm
from vacancies import build_questions

router = Router(name="vacancy")


@router.callback_query(ApplyForm.choosing_vacancy, F.data.startswith("vacancy:"))
async def choose_vacancy(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)

    # Rus tili tanlangan bo'lsa, savollar birinchi marta AI orqali tarjima
    # qilinadi va keyingi safarlar uchun bazada saqlanadi.
    vacancy = await database.get_vacancy_localized(key, lang)
    if not vacancy or not vacancy["active"]:
        await callback.answer(t("vacancy_gone", lang), show_alert=True)
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
        vacancy_questions=build_questions(vacancy, lang),
        question_index=0,
        answers={},
        ai_scores={},
        irrelevant_retry_count=0,
        ai_suspect_retry_count=0,
        followup_asked_indices=[],
        awaiting_followup_for=None,
    )
    await callback.message.edit_text(t("vacancy_selected", lang, title=vacancy["title"]))

    from handlers.resume_upfront import ask_resume_upfront

    await ask_resume_upfront(callback.message, state)
    await callback.answer()
