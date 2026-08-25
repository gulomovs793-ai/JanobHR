"""Janob HR Bot — vakansiya tanlash bosqichi."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from i18n import DEFAULT_LANG, t
from services import database
from states import ApplyForm
from vacancies import build_questions

router = Router(name="vacancy")


async def prepare_vacancy_state(state: FSMContext, tenant_id: int, key: str, lang: str) -> dict | None:
    """Vakansiyani FSM holatiga tayyorlaydi (savollar, rad etish xabari va h.k.).
    Topilmasa/nofaol bo'lsa None qaytaradi. Ham oddiy ro'yxatdan tanlash, ham
    to'g'ridan-to'g'ri havola (deep-link) orqali kirishda ishlatiladi."""
    vacancy = await database.get_vacancy_localized(tenant_id, key, lang)
    if not vacancy or not vacancy["active"]:
        return None

    await state.update_data(
        tenant_id=tenant_id,
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
    return vacancy


@router.callback_query(ApplyForm.choosing_vacancy, F.data.startswith("vacancy:"))
async def choose_vacancy(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)

    vacancy = await prepare_vacancy_state(state, tenant_id, key, lang)
    if not vacancy:
        await callback.answer(t("vacancy_gone", lang), show_alert=True)
        return

    await callback.message.edit_text(t("vacancy_selected", lang, title=vacancy["title"]))

    from handlers.resume_upfront import ask_resume_upfront

    await ask_resume_upfront(callback.message, state)
    await callback.answer()
