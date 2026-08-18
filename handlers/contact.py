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

from states import ApplyForm

logger = logging.getLogger("janob_hr_bot")

router = Router(name="contact")

# Juda soddalashtirilgan telefon raqami tekshiruvi: kamida 7 ta raqam bo'lishi kerak.
_PHONE_DIGITS_RE = re.compile(r"\d")


async def ask_full_name(message: Message, state: FSMContext):
    """Savollar (va fayl, agar kerak bo'lsa) tugagach chaqiriladi."""
    await message.answer(
        "Deyarli tayyor! 🙌 Iltimos, to'liq ism-familiyangizni yozing "
        "(masalan: Aliyev Vali)."
    )
    await state.set_state(ApplyForm.waiting_full_name)


@router.message(ApplyForm.waiting_full_name, F.text)
async def handle_full_name(message: Message, state: FSMContext):
    full_name = message.text.strip()

    if len(full_name) < 3 or not any(ch.isalpha() for ch in full_name):
        await message.answer("Iltimos, to'liq ism va familiyangizni yozing (masalan: Aliyev Vali).")
        return

    await state.update_data(candidate_full_name=full_name)

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamni ulashish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Rahmat! Endi telefon raqamingizni ulashing — pastdagi tugmani bosing, "
        "yoki qo'lda yozib yuboring (masalan: +998901234567).",
        reply_markup=keyboard,
    )
    await state.set_state(ApplyForm.waiting_phone)


@router.message(ApplyForm.waiting_full_name)
async def handle_wrong_name_type(message: Message):
    await message.answer("Iltimos, ism-familiyangizni oddiy matn ko'rinishida yozing.")


async def _finish_contact_collection(message: Message, state: FSMContext, phone: str):
    from handlers.questions import complete_application

    await state.update_data(candidate_phone=phone)
    await message.answer("Rahmat! ✅", reply_markup=ReplyKeyboardRemove())
    await complete_application(message, state)


@router.message(ApplyForm.waiting_phone, F.contact)
async def handle_phone_contact(message: Message, state: FSMContext):
    await _finish_contact_collection(message, state, message.contact.phone_number)


@router.message(ApplyForm.waiting_phone, F.text)
async def handle_phone_text(message: Message, state: FSMContext):
    text = message.text.strip()
    digit_count = len(_PHONE_DIGITS_RE.findall(text))

    if digit_count < 7:
        await message.answer(
            "Bu telefon raqamiga o'xshamayapti. Iltimos, pastdagi tugmani bosing yoki "
            "raqamni to'liq formatda yozing (masalan: +998901234567)."
        )
        return

    await _finish_contact_collection(message, state, text)


@router.message(ApplyForm.waiting_phone)
async def handle_wrong_phone_type(message: Message):
    await message.answer(
        "Iltimos, telefon raqamingizni pastdagi tugma orqali yuboring yoki matn ko'rinishida yozing."
    )
