"""
Janob HR Bot — /start, /cancel: til tanlash, nomzodni kutib olish va oqimni
boshqarish. KO'P MIJOZLI: /start bosilganda, agar yuboruvchi shu mijozning
admin ro'yxatida bo'lsa — Admin menyu, aks holda — nomzod oqimi ko'rsatiladi
(bitta bot, ikkala rol).
"""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from i18n import CHOOSE_LANGUAGE_PROMPT, DEFAULT_LANG, LANGUAGES, t
from services import database
from states import ApplyForm

router = Router(name="start")


async def _show_vacancy_menu(message: Message, state: FSMContext, lang: str, tenant_id: int):
    tenant = await database.get_tenant(tenant_id)
    if tenant and tenant["status"] == "trial_expired":
        pause_text = {
            "uz": "Hozircha yangi arizalar qabul qilinmayapti. Iltimos, birozdan so'ng qayta urinib ko'ring.",
            "ru": "Сейчас новые заявки не принимаются. Пожалуйста, попробуйте позже.",
        }.get(lang, "Hozircha yangi arizalar qabul qilinmayapti. Iltimos, birozdan so'ng qayta urinib ko'ring.")
        await message.answer(pause_text)
        return

    vacancies = await database.list_vacancies_localized(tenant_id, lang, active_only=True)
    greeting = t("greeting", lang)

    if not vacancies:
        await message.answer(t("no_vacancies", lang, greeting=greeting))
        return

    builder = InlineKeyboardBuilder()
    for v in vacancies:
        builder.button(text=v["title"], callback_data=f"vacancy:{v['key']}")
    builder.adjust(1)

    await message.answer(
        t("vacancy_list_prompt", lang, greeting=greeting), reply_markup=builder.as_markup()
    )
    await state.set_state(ApplyForm.choosing_vacancy)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()

    try:
        await database.record_bot_start(tenant_id, message.from_user.id)
    except Exception:
        pass  # Statistika yozib bolmasa ham, botning ishlashiga xalaqit bermasin.

    builder = InlineKeyboardBuilder()
    for code, label in LANGUAGES.items():
        builder.button(text=label, callback_data=f"lang:{code}")
    builder.adjust(1)

    await message.answer(CHOOSE_LANGUAGE_PROMPT, reply_markup=builder.as_markup())
    await state.set_state(ApplyForm.choosing_language)


@router.callback_query(ApplyForm.choosing_language, F.data.startswith("lang:"))
async def choose_language(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    lang = callback.data.split(":", 1)[1]
    if lang not in LANGUAGES:
        lang = DEFAULT_LANG

    await state.update_data(lang=lang)
    await callback.message.delete()

    # --- Takroriy ariza himoyasi: nomzodning ko'rib chiqilayotgan arizasi bo'lsa,
    # unga yangi anketa boshlash o'rniga hozirgi holatini eslatamiz. ---
    pending = await database.get_pending_application_for_user(tenant_id, callback.from_user.id)
    if pending:
        await callback.message.answer(
            t("pending_application_notice", lang, vacancy_title=pending["vacancy_title"])
        )
        await callback.answer()
        return

    await _show_vacancy_menu(callback.message, state, lang, tenant_id)
    await callback.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    current_state = await state.get_state()
    if current_state is None:
        await message.answer(t("cancel_no_active", lang))
        return

    await state.clear()
    await message.answer(t("cancel_done", lang))


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await message.answer(t("help_text", lang))
