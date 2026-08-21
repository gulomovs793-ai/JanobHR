"""
Janob HR — "O'z HR botingizni yarating" bo'limi.

Joriy botni sinab ko'rgan HAR QANDAY kishi (nomzod yoki oddiy qiziquvchi)
shu bo'lim orqali o'ziga shu tizimning nusxasini buyurtma qilishi mumkin.
Bu — alohida "sozlash boti" o'rniga, ALLAQACHON ISHLAYOTGAN, ishonch
uyg'otgan botning o'zida joylashgan CTA (harakatga chaqiruv).

MUHIM: bu bo'lim mavjud nomzod-ariza oqimiga (handlers/questions.py va h.k.)
HECH QANDAY TA'SIR QILMAYDI — butunlay mustaqil FSM holatlari va router
orqali ishlaydi.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from config import FOUNDER_USER_IDS
from services import database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="create_bot")


class CreateBotForm(StatesGroup):
    waiting_company_name = State()
    waiting_token = State()


@router.message(Command("create_bot"))
async def cmd_create_bot(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🚀 <b>O'z HR botingizni yarating!</b>\n\n"
        "Hozir siz sinab ko'rgan aynan shu tizimni — AI orqali nomzodlarni "
        "avtomatik saralaydigan botni — o'z kompaniyangiz uchun bir necha "
        "daqiqada sozlab beramiz.\n\n"
        "Avval, kompaniyangiz nomini yozing:"
    )
    await state.set_state(CreateBotForm.waiting_company_name)


@router.message(CreateBotForm.waiting_company_name, F.text)
async def receive_company_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Iltimos, to'liq kompaniya nomini kiriting.")
        return

    await state.update_data(company_name=name)
    await message.answer(
        "Ajoyib! Endi @BotFather orqali yaratgan botingizning <b>TOKENINI</b> yuboring.\n\n"
        "Agar hali botingiz bo'lmasa: @BotFather ga o'ting, <code>/newbot</code> yuboring, "
        "ism va username bering — sizga token beradi. O'sha tokenni shu yerga joylashtiring."
    )
    await state.set_state(CreateBotForm.waiting_token)


@router.message(CreateBotForm.waiting_token, F.text)
async def receive_token(message: Message, state: FSMContext):
    token = message.text.strip()

    try:
        existing = await database.get_tenant_by_token(token)
    except Exception:
        logger.exception("Tenant tekshirishda kutilmagan xato.")
        await message.answer("⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring.")
        return

    if existing:
        await message.answer(
            "Bu token allaqachon ro'yxatdan o'tgan. Agar bu xato deb hisoblasangiz, "
            "biz bilan bevosita bog'laning."
        )
        return

    wait_msg = await message.answer("🔍 Tokenni tekshiryapman...")

    test_bot = None
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
    except Exception:
        await wait_msg.edit_text(
            "❌ Bu token noto'g'ri yoki ishlamayapti. Iltimos, @BotFather'dan to'g'ri "
            "tokenni nusxalab, qayta yuboring."
        )
        return
    finally:
        if test_bot is not None:
            await test_bot.session.close()

    data = await state.get_data()
    admin_id = message.from_user.id

    try:
        tenant_id = await database.create_tenant(
            company_name=data["company_name"], bot_token=token,
            admin_user_ids=[admin_id], referred_by_user_id=admin_id,
        )
    except Exception:
        logger.exception("Mijozni bazaga yozishda kutilmagan xato.")
        await wait_msg.edit_text("⚠️ Texnik xatolik yuz berdi. Iltimos, /create_bot bilan qayta urinib ko'ring.")
        return

    await wait_msg.edit_text(
        f"✅ Tabriklaymiz! <b>@{me.username}</b> boti muvaffaqiyatli ro'yxatdan o'tkazildi.\n\n"
        f"Buyurtma raqamingiz: <code>{tenant_id}</code>\n\n"
        "To'lov va faollashtirish bo'yicha tez orada siz bilan bog'lanamiz."
    )
    await state.clear()

    logger.info(
        "Joriy bot orqali yangi buyurtma: id=%s, kompaniya=%s, bot=@%s, referal=%s",
        tenant_id, data["company_name"], me.username, admin_id,
    )

    if FOUNDER_USER_IDS:
        notice = (
            f"🆕 <b>Yangi buyurtma (joriy bot orqali)!</b>\n\n"
            f"№{tenant_id} — {data['company_name']}\n"
            f"Bot: @{me.username}\n"
            f"Kim orqali: <code>{admin_id}</code> (bizning botimizni sinab ko'rgan kishi)"
        )
        for founder_id in FOUNDER_USER_IDS:
            try:
                await message.bot.send_message(chat_id=founder_id, text=notice)
            except Exception:
                logger.exception("Asoschiga (id=%s) bildirishnoma yuborib bo'lmadi.", founder_id)


@router.message(CreateBotForm.waiting_token)
async def wrong_token_type(message: Message, state: FSMContext):
    await message.answer("Iltimos, tokenni oddiy matn ko'rinishida yuboring.")
