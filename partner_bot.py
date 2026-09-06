"""Janob HR Partner Bot.

Maqsad:
- SMM/targetolog/agentlik/blogger hamkorlarga avval ularning muammosi va foydasini tushuntirish;
- founder tasdig'idan keyin unique referral link berish;
- partnerga tayyor matnlar va statistikani ko'rsatish;
- biznes leadni Setup botga uzatish.

PARTNER_BOT_TOKEN va PARTNER_REFERRAL_TARGET_USERNAME env orqali beriladi.
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from config import FOUNDER_USER_IDS
from services import partner_database as pdb

logger = logging.getLogger("janob_hr_partner")
router = Router(name="partner")

PARTNER_BOT_TOKEN = os.getenv("PARTNER_BOT_TOKEN", "").strip()
PARTNER_REFERRAL_TARGET_USERNAME = os.getenv(
    "PARTNER_REFERRAL_TARGET_USERNAME", ""
).strip().lstrip("@")

ROLE_LABELS = {
    "targetolog": "🎯 Targetolog",
    "smm": "📱 SMM manager",
    "agency": "🏢 Agentlik",
    "blogger": "🎥 Blogger",
    "other": "👤 Boshqa",
}

COMMISSION_TEXT = (
    "💰 <b>Hamkorlik komissiyasi</b>\n\n"
    "START — 99 000 UZS\n"
    "GROWTH — 199 000 UZS\n"
    "BUSINESS — 299 000 UZS\n\n"
    "Siz mijozni olib kelasiz. Mahsulotni tushuntirish, onboarding va xizmat ko'rsatishni Janob HR jamoasi bajaradi.\n\n"
    "Komissiya mijozning haqiqiy to'lovi tasdiqlangandan keyin hisoblanadi."
)


class PartnerForm(StatesGroup):
    role = State()
    has_clients = State()
    client_band = State()
    phone = State()


def role_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Targetolog", callback_data="role:targetolog")],
            [InlineKeyboardButton(text="📱 SMM manager", callback_data="role:smm")],
            [InlineKeyboardButton(text="🏢 Agentlik", callback_data="role:agency")],
            [InlineKeyboardButton(text="🎥 Blogger", callback_data="role:blogger")],
            [InlineKeyboardButton(text="👤 Boshqa", callback_data="role:other")],
        ]
    )


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🔗 Mening referral linkim")],
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="💰 Komissiya")],
            [KeyboardButton(text="📦 Reklama materiallari")],
            [KeyboardButton(text="🆘 Yordam")],
        ],
        resize_keyboard=True,
    )


def founder_review_keyboard(partner_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data=f"partner_approve:{partner_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish", callback_data=f"partner_reject:{partner_id}"
                ),
            ]
        ]
    )


async def send_partner_home(message: Message, partner: dict) -> None:
    await message.answer(
        "🤝 <b>Janob HR Hamkor</b>\n\n"
        "Sizning hamkor profilingiz faol. Endi biznesga kerak bo'ladigan HR yechimini "
        "o'zingiz yaratmasdan va xizmat ko'rsatmasdan taklif qilishingiz mumkin.\n\n"
        "Mijoz Janob HR tarifini sotib olsa — sizga komissiya hisoblanadi.",
        reply_markup=main_menu(),
    )


async def handle_referral_entry(message: Message, code: str) -> bool:
    partner = await pdb.get_partner_by_code(code.upper())
    if not partner:
        return False

    await pdb.record_referral_click(partner["id"], message.from_user.id)

    if PARTNER_REFERRAL_TARGET_USERNAME:
        target_url = f"https://t.me/{PARTNER_REFERRAL_TARGET_USERNAME}?start=ref_{code.upper()}"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🎁 5 ta bepul ariza bilan boshlash", url=target_url)]
            ]
        )
        await message.answer(
            "👔 <b>Xodim qidirishda eng ko'p vaqt nimaga ketadi?</b>\n\n"
            "Ko'p nomzod yozadi, lekin kim yaxshi ekanini bilish uchun har biri bilan gaplashish, "
            "savol berish va solishtirishga vaqt ketadi.\n\n"
            "<b>Janob HR nima qiladi?</b>\n"
            "Nomzodlarni qabul qiladi, savollar beradi, AI bilan baholaydi va kuchli nomzodlarni "
            "sizga ajratib beradi.\n\n"
            "🎁 Birinchi 5 ta ariza bepul — avval natijani ko'rib, keyin qaror qilasiz.",
            reply_markup=kb,
        )
    else:
        await message.answer(
            "👔 Janob HR referral qabul qilindi. Setup bot manzili hali sozlanmagan."
        )
    return True


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) == 2 and args[1].startswith("r_"):
        if await handle_referral_entry(message, args[1][2:]):
            return

    await state.clear()
    partner = await pdb.get_partner_by_user_id(message.from_user.id)
    if partner:
        if partner["status"] == "approved":
            await send_partner_home(message, partner)
            return
        if partner["status"] == "pending":
            await message.answer(
                "⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach bot sizga shaxsiy referral link beradi."
            )
            return
        if partner["status"] == "rejected":
            await message.answer(
                "Arizangiz hozircha tasdiqlanmagan. Ma'lumotlarni yangilab qayta topshirishingiz mumkin.\n\n"
                "Boshlash uchun kasbingizni tanlang:",
                reply_markup=role_keyboard(),
            )
            await state.set_state(PartnerForm.role)
            return

    await message.answer(
        "🤝 <b>Biznes mijozlaringiz bor, lekin ulardan faqat o'z xizmatingiz orqali daromad qilasizmi?</b>\n\n"
        "Mijozingiz ertaga xodim qidirsa, bu uning katta muammosi — lekin odatda siz bundan daromad olmaysiz.\n\n"
        "<b>Janob HR hamkorlik dasturi shu imkoniyatni beradi:</b>\n"
        "• mijozga tayyor HR yechimini tavsiya qilasiz;\n"
        "• mahsulotni yaratish, tushuntirish va xizmat ko'rsatishni biz qilamiz;\n"
        "• mijoz tarif sotib olsa, siz komissiya olasiz.\n\n"
        "START — 99 000 UZS\n"
        "GROWTH — 199 000 UZS\n"
        "BUSINESS — 299 000 UZS komissiya.\n\n"
        "Sizga yangi xizmat yaratish ham, HR mutaxassisi bo'lish ham shart emas.\n\n"
        "Avval sizga mos kelishini bilib olaylik. <b>Siz kimsiz?</b>",
        reply_markup=role_keyboard(),
    )
    await state.set_state(PartnerForm.role)


@router.callback_query(PartnerForm.role, F.data.startswith("role:"))
async def choose_role(callback: CallbackQuery, state: FSMContext) -> None:
    role = callback.data.split(":", 1)[1]
    if role not in ROLE_LABELS:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(role=role)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Ha", callback_data="clients:yes")],
            [InlineKeyboardButton(text="❌ Hozircha yo'q", callback_data="clients:no")],
        ]
    )
    await callback.message.edit_text(
        f"Tanlandi: <b>{ROLE_LABELS[role]}</b>\n\n"
        "Bu model ayniqsa biznes egalari bilan allaqachon aloqasi bor odamlar uchun kuchli: "
        "mijozga sizda yo'q xizmat kerak bo'lganda uni rad etish o'rniga Janob HR'ga yo'naltirasiz.\n\n"
        "Hozir siz bilan ishlaydigan yoki to'g'ridan-to'g'ri tanish biznes mijozlar bormi?",
        reply_markup=kb,
    )
    await state.set_state(PartnerForm.has_clients)
    await callback.answer()


@router.callback_query(PartnerForm.has_clients, F.data.startswith("clients:"))
async def choose_has_clients(callback: CallbackQuery, state: FSMContext) -> None:
    has_clients = callback.data.endswith("yes")
    await state.update_data(has_clients=has_clients)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="0", callback_data="band:0")],
            [InlineKeyboardButton(text="1–3", callback_data="band:1-3")],
            [InlineKeyboardButton(text="4–10", callback_data="band:4-10")],
            [InlineKeyboardButton(text="10+", callback_data="band:10+")],
        ]
    )
    intro = (
        "Zo'r. Siz uchun asosiy imkoniyat — mavjud mijozlardan qo'shimcha daromad olish.\n\n"
        if has_clients
        else "Muammo emas. Hamkorlik uchun hozir mijoz bo'lishi shart emas — biz sizga tayyor matn va referral link beramiz.\n\n"
    )
    await callback.message.edit_text(
        intro + "Oyiga taxminan nechta biznes bilan ishlaysiz yoki to'g'ridan-to'g'ri aloqangiz bor?",
        reply_markup=kb,
    )
    await state.set_state(PartnerForm.client_band)
    await callback.answer()


@router.callback_query(PartnerForm.client_band, F.data.startswith("band:"))
async def choose_band(callback: CallbackQuery, state: FSMContext) -> None:
    band = callback.data.split(":", 1)[1]
    if band not in {"0", "1-3", "4-10", "10+"}:
        await callback.answer("Noto'g'ri tanlov", show_alert=True)
        return
    await state.update_data(client_band=band)
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(
        "Yaxshi. Tasdiqlansangiz sizga shaxsiy referral link, tayyor sotuv matnlari va "
        "natijalarni kuzatish statistikasi beriladi.\n\n"
        "Oxirgi qadam: bog'lanish uchun telefon raqamingizni yuboring.",
        reply_markup=kb,
    )
    await state.set_state(PartnerForm.phone)
    await callback.answer()


@router.message(PartnerForm.phone, F.contact)
async def receive_phone(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    partner = await pdb.upsert_application(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username or "",
        phone=message.contact.phone_number,
        role=data["role"],
        has_business_clients=bool(data["has_clients"]),
        client_band=data["client_band"],
    )
    await state.clear()
    await message.answer(
        "✅ Arizangiz yuborildi.\n\n"
        "Tasdiqlangach sizga tayyor tizim ochiladi: referral link → mijoz Janob HR'ni sinaydi → "
        "tarif sotib olsa komissiya sizga yoziladi.\n\n"
        "Siz mahsulot yaratmaysiz va mijozga HR xizmatini o'zingiz ko'rsatishingiz shart emas.",
        reply_markup=ReplyKeyboardRemove(),
    )

    notice = (
        "🤝 <b>Yangi partner arizasi</b>\n\n"
        f"#{partner['id']} — {partner['full_name']}\n"
        f"Rol: {ROLE_LABELS.get(partner['role'], partner['role'])}\n"
        f"Biznes mijozlari: {'Ha' if partner['has_business_clients'] else 'Yo‘q'}\n"
        f"Aloqalar: {partner['client_band']}\n"
        f"Telefon: <code>{partner['phone']}</code>\n"
        f"Telegram: @{partner['username'] or '—'}"
    )
    for founder_id in FOUNDER_USER_IDS:
        try:
            await message.bot.send_message(
                founder_id, notice, reply_markup=founder_review_keyboard(partner["id"])
            )
        except Exception:
            logger.exception("Founderga partner arizasini yuborib bo'lmadi: %s", founder_id)


@router.message(PartnerForm.phone)
async def wrong_phone(message: Message) -> None:
    await message.answer("Pastdagi «📱 Telefon raqamni yuborish» tugmasini bosing.")


@router.callback_query(F.data.startswith("partner_approve:"))
async def approve_partner(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    partner_id = int(callback.data.split(":", 1)[1])
    partner = await pdb.set_partner_status(partner_id, "approved")
    if not partner:
        await callback.answer("Partner topilmadi", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"✅ Partner #{partner_id} tasdiqlandi.")
    try:
        await callback.bot.send_message(
            partner["telegram_user_id"],
            "🎉 <b>Hamkorligingiz tasdiqlandi!</b>\n\n"
            "Endi sizda yangi daromad kanali bor: biznesni Janob HR'ga yo'naltirasiz, "
            "qolgan jarayonni biz bajaramiz.\n\n"
            "Quyidagi menyudan referral linkingiz va tayyor materiallarni oling.",
            reply_markup=main_menu(),
        )
    except Exception:
        logger.exception("Tasdiqlangan partnerga xabar yuborilmadi: %s", partner_id)
    await callback.answer("Tasdiqlandi")


@router.callback_query(F.data.startswith("partner_reject:"))
async def reject_partner(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    partner_id = int(callback.data.split(":", 1)[1])
    partner = await pdb.set_partner_status(partner_id, "rejected")
    if not partner:
        await callback.answer("Partner topilmadi", show_alert=True)
        return
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Partner #{partner_id} rad etildi.")
    try:
        await callback.bot.send_message(
            partner["telegram_user_id"],
            "Arizangiz hozircha tasdiqlanmadi. Keyinroq /start orqali ma'lumotlarni yangilab qayta topshirishingiz mumkin.",
        )
    except Exception:
        logger.exception("Rad etilgan partnerga xabar yuborilmadi: %s", partner_id)
    await callback.answer("Rad etildi")


async def require_approved(message: Message) -> dict | None:
    partner = await pdb.get_partner_by_user_id(message.from_user.id)
    if not partner or partner["status"] != "approved":
        await message.answer("Bu bo'lim faqat tasdiqlangan partnerlar uchun. /start yuboring.")
        return None
    return partner


@router.message(F.text == "🔗 Mening referral linkim")
async def my_link(message: Message, bot: Bot) -> None:
    partner = await require_approved(message)
    if not partner:
        return
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=r_{partner['referral_code']}"
    await message.answer(
        "🔗 <b>Sizning shaxsiy linkingiz</b>\n\n"
        f"<code>{link}</code>\n\n"
        "Mijoz aynan shu link orqali kirsa, sizning referral sifatida qayd qilinadi."
    )


@router.message(F.text == "📊 Statistika")
async def statistics(message: Message) -> None:
    partner = await require_approved(message)
    if not partner:
        return
    stats = await pdb.get_partner_stats(partner["id"])
    await message.answer(
        "📊 <b>Partner statistikasi</b>\n\n"
        f"Referral kirishlar: <b>{stats['clicks']}</b>\n"
        f"Trial boshlaganlar: <b>{stats['trials']}</b>\n"
        f"Sotuvlar: <b>{stats['sales']}</b>\n"
        f"Hisoblangan komissiya: <b>{stats['earned']:,} UZS</b>".replace(",", " ")
    )


@router.message(F.text == "💰 Komissiya")
async def commission(message: Message) -> None:
    if await require_approved(message):
        await message.answer(COMMISSION_TEXT)


@router.message(F.text == "📦 Reklama materiallari")
async def materials(message: Message) -> None:
    if not await require_approved(message):
        return
    await message.answer(
        "📦 <b>Tayyor reklama materiallari</b>\n\n"
        "<b>1. Story matni</b>\n"
        "Xodim topish uchun yuzlab CV ko'rishga vaqt ketayaptimi? Janob HR nomzodlarni qabul qiladi, savollar beradi va AI bilan saralaydi. Birinchi 5 ta ariza bepul. Link orqali sinab ko'ring.\n\n"
        "<b>2. Biznes egasiga shaxsiy xabar</b>\n"
        "Assalomu alaykum. Xodim yollash jarayonini yengillashtiradigan Janob HR degan tizim bor. Nomzodlarni avtomatik qabul qilib, baholab beradi. 5 ta ariza bepul, xohlasangiz link yuboraman.\n\n"
        "<b>3. Qisqa hook</b>\n"
        "Har bir nomzod bilan alohida gaplashishni to'xtating — Janob HR birinchi saralashni siz uchun qiladi."
    )


@router.message(F.text == "🆘 Yordam")
async def help_section(message: Message) -> None:
    if await require_approved(message):
        await message.answer(
            "🆘 Savol bo'lsa shu chatga yozing. Founder jamoasi partner profilingiz orqali siz bilan bog'lanadi."
        )


async def main() -> None:
    if not PARTNER_BOT_TOKEN:
        raise RuntimeError("PARTNER_BOT_TOKEN sozlanmagan")
    await pdb.init_partner_db()
    bot = Bot(
        token=PARTNER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Janob HR Partner Bot ishga tushdi")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
