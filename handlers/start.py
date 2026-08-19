"""Janob HR Bot — /start, /cancel: nomzodni kutib olish va oqimni boshqarish."""
from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database
from states import ApplyForm

router = Router(name="start")


async def _show_vacancy_menu(message: Message, state: FSMContext, greeting: str):
    vacancies = await database.list_vacancies(active_only=True)

    if not vacancies:
        await message.answer(
            f"{greeting}\n\nHozircha ochiq vakansiyalar yo'q. Iltimos, keyinroq qayta urinib ko'ring."
        )
        return

    builder = InlineKeyboardBuilder()
    for v in vacancies:
        builder.button(text=v["title"], callback_data=f"vacancy:{v['key']}")
    builder.adjust(1)

    await message.answer(f"{greeting}\n\nQuyidagi vakansiyalardan birini tanlang:", reply_markup=builder.as_markup())
    await state.set_state(ApplyForm.choosing_vacancy)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    # --- Takroriy ariza himoyasi: nomzodning ko'rib chiqilayotgan arizasi bo'lsa,
    # unga yangi anketa boshlash o'rniga hozirgi holatini eslatamiz. ---
    pending = await database.get_pending_application_for_user(message.from_user.id)
    if pending:
        await message.answer(
            f"👋 Assalomu alaykum! Sizning <b>{pending['vacancy_title']}</b> vakansiyasiga "
            "yuborgan arizangiz hozircha ko'rib chiqilmoqda.\n\n"
            "Natija haqida tez orada shu yerda xabar beramiz — hozircha yangi ariza "
            "topshirishning hojati yo'q. Agar shoshilinch savolingiz bo'lsa, operator bilan "
            "bog'laning."
        )
        return

    await _show_vacancy_menu(
        message, state,
        "👋 Assalomu alaykum! <b>Janob HR</b> bot orqali vakansiyaga ariza topshirishingiz mumkin.",
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Hozir bekor qilinadigan faol ariza yo'q. /start bilan boshlashingiz mumkin.")
        return

    await state.clear()
    await message.answer("❌ Ariza bekor qilindi. Qaytadan boshlash uchun /start yuboring.")


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "🤖 <b>Janob HR bot</b>\n\n"
        "/start — vakansiyaga ariza topshirishni boshlash\n"
        "/cancel — joriy arizani bekor qilish\n"
        "/help — shu xabarni ko'rsatish"
    )
