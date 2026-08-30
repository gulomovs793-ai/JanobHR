"""
Janob HR — "O'z HR botingizni yarating" bo'limi.

Joriy botni sinab ko'rgan HAR QANDAY kishi shu bo'lim orqali o'ziga shu
tizimning nusxasini buyurtma qilishi mumkin. Har bir mijoz IKKITA alohida
bot yaratadi: bittasi nomzodlar bilan ishlaydigan bot, ikkinchisi — faqat
o'zining administratorlari ishlatadigan Admin panel-bot.
"""

import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from config import ADMIN_BOT_TOKEN, ADMIN_USER_IDS, FOUNDER_USER_IDS
from services import bot_registry, database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="create_bot")


async def _send_to_janob_hr_admin(text: str) -> None:
    """Biznes leadlarni faqat Janob HR Admin bot orqali yuboradi."""
    recipient_ids = ADMIN_USER_IDS or FOUNDER_USER_IDS
    if not recipient_ids:
        logger.error("Biznes lead uchun ADMIN_USER_IDS sozlanmagan.")
        return

    admin_bot = bot_registry.admin_bot
    temporary_bot = None
    if admin_bot is None:
        if not ADMIN_BOT_TOKEN:
            logger.error("Biznes lead uchun ADMIN_BOT_TOKEN sozlanmagan.")
            return
        temporary_bot = Bot(
            token=ADMIN_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        admin_bot = temporary_bot

    try:
        for admin_id in recipient_ids:
            try:
                await admin_bot.send_message(chat_id=admin_id, text=text)
            except Exception:
                logger.exception(
                    "Biznes leadni Janob HR Admin orqali yuborib bo'lmadi: %s",
                    admin_id,
                )
    finally:
        if temporary_bot is not None:
            await temporary_bot.session.close()


class CreateBotForm(StatesGroup):
    waiting_hiring_problem = State()
    waiting_current_process = State()
    waiting_desired_result = State()
    waiting_company_name = State()
    waiting_contact = State()
    waiting_candidate_token = State()
    waiting_admin_token = State()


async def _validate_token(token: str) -> str | None:
    """Token to'g'ri ishlasa, bot username'ini qaytaradi; aks holda None."""
    test_bot = None
    try:
        test_bot = Bot(token=token)
        me = await test_bot.get_me()
        return me.username
    except Exception:  # noqa: BLE001 - noto'g'ri token turli aiogram xatolarini beradi
        return None
    finally:
        if test_bot is not None:
            await test_bot.session.close()


async def _start_business_flow(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Har bir kompaniyada xodim yollashdagi asosiy muammo har xil bo'ladi: "
        "ba'zilarida mos nomzod topish, ba'zilarida saralashga ketadigan vaqt, "
        "boshqalarida esa ishga olingan xodimning uzoq ishlamasligi muammo bo'ladi.\n\n"
        "<b>Hozir orzuyingizdagi xodimni yollashda sizni eng ko'p qiynayotgan "
        "narsa nima?</b>"
    )
    await state.set_state(CreateBotForm.waiting_hiring_problem)


@router.message(Command("create_bot"))
async def cmd_create_bot(message: Message, state: FSMContext):
    await _start_business_flow(message, state)


@router.callback_query(F.data == "business:start")
async def start_business_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await _start_business_flow(callback.message, state)


@router.callback_query(F.data == "business:skip")
async def skip_business_callback(callback: CallbackQuery):
    await callback.answer("Mayli, istalgan vaqtda /create_bot buyrug'ini yuboring.")
    await callback.message.edit_reply_markup(reply_markup=None)


@router.message(CreateBotForm.waiting_hiring_problem, F.text)
async def receive_hiring_problem(message: Message, state: FSMContext):
    value = message.text.strip()
    if len(value) < 2:
        await message.answer("Muammoni qisqacha yozib bering.")
        return
    await state.update_data(hiring_problem=value)
    await message.answer("Odatda ishingizga qiziqqan nomzodlarni qanday saralaysiz?")
    await state.set_state(CreateBotForm.waiting_current_process)


@router.message(CreateBotForm.waiting_current_process, F.text)
async def receive_current_process(message: Message, state: FSMContext):
    value = message.text.strip()
    if len(value) < 2:
        await message.answer("Hozirgi saralash jarayoningizni qisqacha yozing.")
        return
    await state.update_data(current_process=value)
    await message.answer(
        "Qaysi muammoyingizni hal qilib bersak, Janob HR bilan muntazam "
        "ishlagan bo'lardingiz?"
    )
    await state.set_state(CreateBotForm.waiting_desired_result)


@router.message(CreateBotForm.waiting_desired_result, F.text)
async def receive_desired_result(message: Message, state: FSMContext):
    value = message.text.strip()
    if len(value) < 2:
        await message.answer("Siz uchun kerakli natijani qisqacha yozing.")
        return
    await state.update_data(desired_result=value)
    data = await state.get_data()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Ha, davom etaman", callback_data="business:trial"
                )
            ],
            [InlineKeyboardButton(text="Hozir emas", callback_data="business:skip")],
        ]
    )
    await message.answer(
        f"Siz aytgan asosiy muammo — <b>{escape(data['hiring_problem'])}</b>.\n\n"
        f"Hozir nomzodlarni <b>{escape(data['current_process'])}</b>, shu sabab "
        "saralashda vaqt va kuch yo'qotyapsiz. Janob HR nomzodlarni bir xil "
        "mezon asosida tekshiradi va sizga eng moslarini ajratib beradi.\n\n"
        "🎁 Buni o'zingiz ko'rish uchun birinchi <b>5 ta ariza BUTUNLAY BEPUL</b>.\n\n"
        "Davom etasizmi?",
        reply_markup=keyboard,
    )
    await state.set_state(None)


@router.callback_query(F.data == "business:trial")
async def start_trial(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Zo'r. Shaxsiy HR botingizni tayyorlash uchun kompaniyangiz nomini yozing."
    )
    await state.set_state(CreateBotForm.waiting_company_name)


@router.message(CreateBotForm.waiting_company_name, F.text)
async def receive_company_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Iltimos, to'liq kompaniya nomini kiriting.")
        return
    await state.update_data(company_name=name)
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Siz bilan bog'lanishimiz uchun telefon raqamingizni yuboring.",
        reply_markup=keyboard,
    )
    await state.set_state(CreateBotForm.waiting_contact)


@router.message(CreateBotForm.waiting_contact, F.contact)
async def receive_contact(message: Message, state: FSMContext):
    await state.update_data(
        contact_name=message.from_user.full_name,
        contact_phone=message.contact.phone_number,
        contact_username=message.from_user.username or "",
    )
    data = await state.get_data()
    await message.answer(
        "✅ <b>Rahmat, ma'lumotlar qabul qilindi.</b>\n\n"
        f"Kompaniya: <b>{escape(data['company_name'])}</b>\n"
        f"Kerakli natija: {escape(data['desired_result'])}\n\n"
        "Endi botlaringizni ulaymiz. 1️⃣-botingiz uchun — @BotFather orqali yaratgan "
        "<b>NOMZOD-BOT</b>ning TOKENINI yuboring.\n\n"
        "Agar hali bo'lmasa: @BotFather ga o'ting, <code>/newbot</code> yuboring, "
        "ism va username bering — sizga token beradi.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(CreateBotForm.waiting_candidate_token)

    notice = (
        "🔥 <b>Yangi biznes lead!</b>\n\n"
        f"Kompaniya: <b>{escape(data['company_name'])}</b>\n"
        f"Muammo: {escape(data['hiring_problem'])}\n"
        f"Hozirgi jarayon: {escape(data['current_process'])}\n"
        f"Kerakli natija: {escape(data['desired_result'])}\n"
        f"Kontakt: {escape(message.from_user.full_name)}\n"
        f"Telefon: <code>{escape(message.contact.phone_number)}</code>\n"
        f"Telegram: @{escape(message.from_user.username or '—')}"
    )
    await _send_to_janob_hr_admin(notice)


@router.message(CreateBotForm.waiting_contact)
async def wrong_contact_type(message: Message):
    await message.answer("Pastdagi «📱 Telefon raqamni yuborish» tugmasini bosing.")


@router.message(CreateBotForm.waiting_candidate_token, F.text)
async def receive_candidate_token(message: Message, state: FSMContext):
    token = message.text.strip()

    try:
        existing = await database.get_tenant_by_token(token)
    except Exception:
        logger.exception("Tenant tekshirishda kutilmagan xato.")
        await message.answer(
            "⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring."
        )
        return

    if existing:
        await message.answer(
            "Bu token allaqachon ro'yxatdan o'tgan. Boshqa tokenmi tekshiring."
        )
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
        await message.answer(
            "⚠️ Texnik xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring."
        )
        return

    if existing:
        await message.answer(
            "Bu token allaqachon ro'yxatdan o'tgan. Boshqa tokenmi tekshiring."
        )
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
            contact_name=data.get("contact_name", message.from_user.full_name),
            contact_phone=data.get("contact_phone", ""),
            contact_username=data.get("contact_username", ""),
        )
    except Exception:
        logger.exception("Mijozni bazaga yozishda kutilmagan xato.")
        await wait_msg.edit_text(
            "⚠️ Texnik xatolik yuz berdi. Iltimos, /create_bot bilan qayta urinib ko'ring."
        )
        return

    await wait_msg.edit_text(
        f"✅ Tabriklaymiz! Ikkala botingiz ham tayyor:\n\n"
        f"1️⃣ Nomzod-bot: @{data['candidate_bot_username']}\n"
        f"2️⃣ Admin panel-bot: @{admin_username}\n\n"
        f"Buyurtma raqamingiz: <code>{tenant_id}</code>\n\n"
        "To'lov va faollashtirish bo'yicha tez orada siz bilan bog'lanamiz."
    )
    await state.clear()

    logger.info(
        "Joriy bot orqali yangi buyurtma: id=%s, kompaniya=%s, nomzod-bot=@%s, admin-bot=@%s",
        tenant_id,
        data["company_name"],
        data["candidate_bot_username"],
        admin_username,
    )

    notice = (
        f"🆕 <b>Yangi buyurtma (2 bot)!</b>\n\n"
        f"№{tenant_id} — {escape(data['company_name'])}\n"
        f"Nomzod-bot: @{escape(data['candidate_bot_username'])}\n"
        f"Admin-bot: @{escape(admin_username)}\n"
        f"Telefon: <code>{escape(data.get('contact_phone') or '—')}</code>\n"
        f"Kim orqali: <code>{admin_id}</code>"
    )
    await _send_to_janob_hr_admin(notice)


@router.message(CreateBotForm.waiting_candidate_token)
@router.message(CreateBotForm.waiting_admin_token)
async def wrong_token_type(message: Message, state: FSMContext):
    await message.answer("Iltimos, tokenni oddiy matn ko'rinishida yuboring.")
