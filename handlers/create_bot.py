"""
Janob HR — "O'z HR botingizni yarating" bo'limi.

Joriy botni sinab ko'rgan HAR QANDAY kishi shu bo'lim orqali o'ziga shu
tizimning nusxasini buyurtma qilishi mumkin. Har bir mijoz IKKITA alohida
bot yaratadi: bittasi nomzodlar bilan ishlaydigan bot, ikkinchisi — faqat
o'zining administratorlari ishlatadigan Admin panel-bot.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from services import database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="create_bot")


class CreateBotForm(StatesGroup):
    waiting_company_name = State()
    waiting_candidate_token = State()
    waiting_admin_token = State()


async def _validate_token(token: str) -> str | None:
    """Token to'g'ri ishlasa, bot username'ini qaytaradi; aks holda None."""
    test_bot = None
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        return me.username
    except Exception:
        return None
    finally:
        if test_bot is not None:
            await test_bot.session.close()


@router.message(Command("create_bot"))
async def cmd_create_bot(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🚀 <b>O'z HR botingizni yarating!</b>\n\n"
        "Hozir siz sinab ko'rgan aynan shu tizimni o'z kompaniyangiz uchun "
        "sozlab beramiz. Sizga IKKITA bot kerak bo'ladi:\n"
        "1️⃣ Nomzodlar ariza topshiradigan bot\n"
        "2️⃣ Faqat sizning o'zingiz (va xodimlaringiz) ishlatadigan Admin panel-bot\n\n"
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
        "Ajoyib! Endi 1️⃣-botingiz uchun — @BotFather orqali yaratgan "
        "<b>NOMZOD-BOT</b>ning TOKENINI yuboring.\n\n"
        "Agar hali bo'lmasa: @BotFather ga o'ting, <code>/newbot</code> yuboring, "
        "ism va username bering — sizga token beradi."
    )
    await state.set_state(CreateBotForm.waiting_candidate_token)


@router.message(CreateBotForm.waiting_candidate_token, F.text)
async def receive_candidate_token(message: Message, state: FSMContext):
    token = message.text.strip()

    try:
        existing = await database.get_tenant_by_token(token)
    except Exception:
        logger.exception("Tenant tekshirishda kutilmagan xato.")
        await message.answer("⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring.")
        return

    if existing:
        await message.answer("Bu token allaqachon ro'yxatdan o'tgan. Boshqa tokenmi tekshiring.")
        return

    wait_msg = await message.answer("🔍 Tokenni tekshiryapman...")
    username = await _validate_token(token)
    if not username:
        await wait_msg.edit_text(
            "❌ Bu token noto'g'ri yoki ishlamayapti. Iltimos, @BotFather'dan to'g'ri "
            "tokenni nusxalab, qayta yuboring."
        )
        return

    await state.update_data(candidate_bot_token=token, candidate_bot_username=username)
    await wait_msg.edit_text(f"✅ 1️⃣-bot tayyor: @{username}")
    await message.answer(
        "Endi 2️⃣-botingiz uchun — <b>ADMIN PANEL-BOT</b>ning TOKENINI yuboring.\n\n"
        "Bu — BUTUNLAY BOSHQA, yangi bot bo'lishi kerak (@BotFather ga yana bir bor "
        "<code>/newbot</code> yuborib, boshqa ism/username bilan yarating)."
    )
    await state.set_state(CreateBotForm.waiting_admin_token)


@router.message(CreateBotForm.waiting_admin_token, F.text)
async def receive_admin_token(message: Message, state: FSMContext):
    token = message.text.strip()
    data = await state.get_data()

    if token == data.get("candidate_bot_token"):
        await message.answer(
            "Bu — 1️⃣-bot uchun ishlatgan tokeningiz. Admin panel-bot uchun "
            "BOSHQA, yangi bot tokeni kerak."
        )
        return

    try:
        existing = await database.get_tenant_by_token(token)
    except Exception:
        logger.exception("Tenant tekshirishda kutilmagan xato.")
        await message.answer("⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring.")
        return

    if existing:
        await message.answer("Bu token allaqachon ro'yxatdan o'tgan. Boshqa tokenmi tekshiring.")
        return

    wait_msg = await message.answer("🔍 Tokenni tekshiryapman...")
    admin_username = await _validate_token(token)
    if not admin_username:
        await wait_msg.edit_text(
            "❌ Bu token noto'g'ri yoki ishlamayapti. Iltimos, @BotFather'dan to'g'ri "
            "tokenni nusxalab, qayta yuboring."
        )
        return

    admin_id = message.from_user.id

    try:
        tenant_id = await database.create_tenant(
            company_name=data["company_name"],
            bot_token=data["candidate_bot_token"],
            admin_bot_token=token,
            admin_user_ids=[admin_id],
        )
    except Exception:
        logger.exception("Mijozni bazaga yozishda kutilmagan xato.")
        await wait_msg.edit_text("⚠️ Texnik xatolik yuz berdi. Iltimos, /create_bot bilan qayta urinib ko'ring.")
        return

    await wait_msg.edit_text(
        f"✅ Ikkala botingiz ham tayyor:\n\n"
        f"1️⃣ Nomzod-bot: @{data['candidate_bot_username']}\n"
        f"2️⃣ Admin panel-bot: @{admin_username}\n\n"
        f"Buyurtma raqamingiz: <code>{tenant_id}</code>"
    )
    await state.clear()

    # --- To'lov ko'rsatmasi: noyob summa bilan, darhol ---
    from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER
    from services.payment_automation import create_payment_order

    if PAYMENT_CARD_NUMBER:
        order = await create_payment_order(tenant_id)
        card_digits = PAYMENT_CARD_NUMBER.replace(" ", "")
        await message.answer(
            f"<b>To'lov ma'lumotlari:</b>\n\n"
            f"💳 Karta: <code>{card_digits}</code>\n"
            f"👤 {PAYMENT_CARD_HOLDER}\n"
            f"💰 Summa: <code>{order['amount']}</code> so'm\n\n"
            f"⚠️ <b>DIQQAT!</b> Aynan <code>{order['amount']}</code> so'm o'tkazing — "
            "1 so'mga ham ko'p yoki kam bo'lmasin, aks holda to'lov avtomatik tasdiqlanmaydi.\n\n"
            "🤖 To'lov tushishi bilan botlaringiz avtomatik faollashadi (odatda 1 daqiqagacha)."
        )
    else:
        await message.answer("To'lov va faollashtirish bo'yicha tez orada siz bilan bog'lanamiz.")

    logger.info(
        "Joriy bot orqali yangi buyurtma: id=%s, kompaniya=%s, nomzod-bot=@%s, admin-bot=@%s",
        tenant_id, data["company_name"], data["candidate_bot_username"], admin_username,
    )

    notice = (
        f"🆕 <b>Yangi buyurtma (2 bot)!</b>\n\n"
        f"№{tenant_id} — {data['company_name']}\n"
        f"Nomzod-bot: @{data['candidate_bot_username']}\n"
        f"Admin-bot: @{admin_username}\n"
        f"Kim orqali: <code>{admin_id}</code>"
    )
    try:
        from services.tenant_activation import notify_founder_admin_panel

        await notify_founder_admin_panel(notice)
    except Exception:
        logger.exception("Asoschiga bildirishnoma yuborib bo'lmadi.")


@router.message(CreateBotForm.waiting_candidate_token)
@router.message(CreateBotForm.waiting_admin_token)
async def wrong_token_type(message: Message, state: FSMContext):
    await message.answer("Iltimos, tokenni oddiy matn ko'rinishida yuboring.")
