"""
Janob HR Bot — nomzoddan yakuniy aloqa ma'lumotlarini (to'liq ism-familiya,
telefon raqami) yig'ish. Barcha savollar (va agar kerak bo'lsa, fayl) qabul
qilingandan so'ng, arizani yakunlashdan oldin shu bosqich ishga tushadi.
"""
import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from i18n import DEFAULT_LANG, t
from states import ApplyForm

logger = logging.getLogger("janob_hr_bot")

router = Router(name="contact")

# Juda soddalashtirilgan telefon raqami tekshiruvi: kamida 7 ta raqam bo'lishi kerak.
_PHONE_DIGITS_RE = re.compile(r"\d")


async def ask_full_name(message: Message, state: FSMContext):
    """Savollar (va fayl, agar kerak bo'lsa) tugagach chaqiriladi."""
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await message.answer(t("ask_full_name", lang))
    await state.set_state(ApplyForm.waiting_full_name)


@router.message(ApplyForm.waiting_full_name, F.text)
async def handle_full_name(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    full_name = message.text.strip()

    if len(full_name) < 3 or not any(ch.isalpha() for ch in full_name):
        await message.answer(t("name_too_short", lang))
        return

    await state.update_data(candidate_full_name=full_name)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=t("share_phone_button", lang), request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(t("ask_phone", lang), reply_markup=keyboard)
    await state.set_state(ApplyForm.waiting_phone)


@router.message(ApplyForm.waiting_full_name)
async def handle_wrong_name_type(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await message.answer(t("wrong_name_type", lang))


async def _finish_contact_collection(message: Message, state: FSMContext, phone: str):
    from handlers.questions import complete_application

    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)

    await state.update_data(candidate_phone=phone)
    await message.answer(t("contact_thanks", lang), reply_markup=ReplyKeyboardRemove())
    await complete_application(message, state)


@router.message(ApplyForm.waiting_phone, F.contact)
async def handle_phone_contact(message: Message, state: FSMContext):
    await _finish_contact_collection(message, state, message.contact.phone_number)


@router.message(ApplyForm.waiting_phone, F.text)
async def handle_phone_text(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    text = message.text.strip()
    digit_count = len(_PHONE_DIGITS_RE.findall(text))

    if digit_count < 7:
        await message.answer(t("phone_invalid", lang))
        return

    await _finish_contact_collection(message, state, text)


@router.message(ApplyForm.waiting_phone)
async def handle_wrong_phone_type(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    await message.answer(t("wrong_phone_type", lang))
