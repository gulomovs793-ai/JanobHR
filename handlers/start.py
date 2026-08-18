"""Janob HR Bot — /start: nomzodni kutib olish va vakansiya tanlashni taklif qilish."""
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from states import ApplyForm
from vacancies import vacancy_keyboard_rows

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    builder = InlineKeyboardBuilder()
    for key, title in vacancy_keyboard_rows():
        builder.button(text=title, callback_data=f"vacancy:{key}")
    builder.adjust(1)

    await message.answer(
        "👋 Assalomu alaykum! <b>Janob HR</b> bot orqali vakansiyaga ariza topshirishingiz mumkin.\n\n"
        "Quyidagi vakansiyalardan birini tanlang:",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(ApplyForm.choosing_vacancy)
