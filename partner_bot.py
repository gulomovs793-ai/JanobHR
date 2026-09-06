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
    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
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


def options_keyboard(prefix: str, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=f"{prefix}:{value}")]
            for label, value in options
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


def question_1(role: str) -> tuple[str, list[tuple[str, str]]]:
    if role in {"targetolog", "smm"}:
        return (
            "1/3. <b>Hozir nechta kompaniya bilan ishlayapsiz?</b>",
            [("0", "0"), ("1–3", "1-3"), ("4–10", "4-10"), ("10+", "10+")],
        )
    if role == "agency":
        return (
            "1/3. <b>Agentligingiz hozir nechta biznes bilan ishlaydi?</b>",
            [("0", "0"), ("1–3", "1-3"), ("4–10", "4-10"), ("10+", "10+")],
        )
    if role == "blogger":
        return (
            "1/4. <b>Auditoriyangizning asosiy qismi kimlar?</b>",
            [("Biznes egalari", "business"), ("Mutaxassislar", "specialists"), ("Aralash auditoriya", "mixed")],
        )
    return (
        "1/3. <b>Biznes egalari bilan qanday aloqangiz bor?</b>",
        [
            ("Ular bilan ishlayman", "work"),
            ("Tanishlarim orasida bor", "friends"),
            ("Ish orqali ko'p uchrashaman", "often"),
            ("Deyarli aloqam yo'q", "none"),
        ],
    )


def question_2(role: str) -> tuple[str, list[tuple[str, str]]]:
    if role in {"targetolog", "smm"}:
        return (
            "2/3. <b>Mijozlaringiz orasida tez-tez xodim qidiradiganlari bormi?</b>",
            [("Ha, tez-tez", "often"), ("Ba'zida", "sometimes"), ("Yo'q", "no")],
        )
    if role == "agency":
        return (
            "2/3. <b>Agentligingiz marketingdan tashqari HR muammolarini ham hal qiladimi?</b>",
            [("Ha", "yes"), ("Ba'zida", "sometimes"), ("Yo'q", "no")],
        )
    if role == "blogger":
        return (
            "2/4. <b>Auditoriyangiz orasida biznes yuritadiganlar bormi?</b>",
            [("Ko'p", "many"), ("Bor", "some"), ("Juda kam", "few")],
        )
    return (
        "2/3. <b>Ijtimoiy tarmoqlarda auditoriyangiz bormi?</b>",
        [("Ha, faol auditoriyam bor", "active"), ("Kichik auditoriyam bor", "small"), ("Yo'q", "none")],
    )


def question_3(role: str) -> tuple[str, list[tuple[str, str]]]:
    if role == "blogger":
        return (
            "3/4. <b>Hozir blogingizdan asosan qanday daromad olasiz?</b>",
            [
                ("Reklama", "ads"),
                ("O'z xizmatim yoki mahsulotim", "own"),
                ("Ikkalasi ham", "both"),
                ("Hozircha daromad qilmayman", "none"),
            ],
        )
    return (
        "3/3. <b>Qo'shimcha daromad taklifi sizga qiziqmi?</b>",
        [("Ha", "yes"), ("Batafsil bilmoqchiman", "details"), ("Hozircha yo'q", "no")],
    )


def question_4(role: str) -> tuple[str, list[tuple[str, str]]]:
    return (
        "4/4. <b>Qo'shimcha daromad taklifi sizga qiziqmi?</b>",
        [("Ha", "yes"), ("Batafsil bilmoqchiman", "details"), ("Hozircha yo'q", "no")],
    )


def build_diagnosis(data: dict) -> str:
    role = data.get("role", "other")
    q1, q2, q3, q4 = data.get("q1"), data.get("q2"), data.get("q3"), data.get("q4")

    if role in {"targetolog", "smm"}:
        profession = "Targetolog" if role == "targetolog" else "SMM manager"
        if q1 == "0":
            opening = (
                f"{profession} sifatida hozir faol biznes mijozlaringiz bo'lmasa ham, sizga hamkorlik yopiq emas. "
                "Sizga tayyor referral link va sotuv matnlari beriladi, shu orqali yangi biznes aloqalarini monetizatsiya qilishingiz mumkin."
            )
        elif q2 == "often":
            opening = (
                f"Siz {profession.lower()} sifatida bizneslar bilan allaqachon ishlaysiz va ularning xodim qidirish muammosini tez-tez ko'rasiz. "
                "Hozir bu muammo sizning daromadingizga aylanmayapti."
            )
        elif q2 == "sometimes":
            opening = (
                f"Sizda biznes mijozlar bilan tayyor aloqa bor. Xodim qidirish muammosi har kuni bo'lmasa ham, paydo bo'lgan paytda sizda unga beradigan tayyor yechim bo'lishi mumkin."
            )
        else:
            opening = (
                f"Sizning asosiy kuchingiz — biznes egalarining sizga bo'lgan ishonchi. Hozir ular HR muammosini ko'p aytmasa ham, ehtiyoj paydo bo'lganda birinchi tavsiya beradigan odam siz bo'lishingiz mumkin."
            )
        return (
            f"🧩 <b>Sizning holatingiz</b>\n\n{opening}\n\n"
            "<b>Janob HR sizga qanday yordam beradi?</b>\n"
            "• mijozga xodimlarni avtomatik qabul qilish va AI bilan saralash yechimini taklif qilasiz;\n"
            "• mahsulotni tushuntirish, onboarding va xizmatni biz bajaramiz;\n"
            "• siz alohida HR xizmatini yaratishingiz shart emas;\n"
            "• mijoz tarif sotib olsa, sizga komissiya hisoblanadi.\n\n"
            "Ya'ni mavjud biznes aloqalaringizdan qo'shimcha daromad kanali ochasiz."
        )

    if role == "agency":
        if q1 in {"4-10", "10+"}:
            scale = "Agentligingizda allaqachon yaxshi biznes mijozlar bazasi bor."
        elif q1 == "1-3":
            scale = "Mijozlar soni katta bo'lmasa ham, sizda hamkorlikni boshlash uchun real biznes aloqalari bor."
        else:
            scale = "Hozir faol mijozlar kam bo'lsa ham, keyingi biznes mijozlar uchun HR yechimini xizmat portfelingizga tayyor qo'shib qo'yishingiz mumkin."

        if q2 == "no":
            gap = "Hozir HR muammolari sizning xizmat doirangizdan tashqarida qoladi — aynan shu joyda qo'shimcha daromad imkoniyati yo'qoladi."
        elif q2 == "sometimes":
            gap = "Siz HR muammolariga ba'zida kirishasiz, lekin uni alohida tizim sifatida yuritmasligingiz mumkin."
        else:
            gap = "Siz HR bilan ham ishlaysiz; Janob HR qo'lda bajariladigan saralash ishini kamaytirib, mavjud xizmatingizni kuchaytirishi mumkin."

        return (
            f"🧩 <b>Agentligingiz uchun imkoniyat</b>\n\n{scale} {gap}\n\n"
            "<b>Janob HR qanday yordam beradi?</b>\n"
            "• agentlik yangi HR mahsulotini noldan qurmaydi;\n"
            "• mijozga tayyor avtomatik saralash tizimini tavsiya qiladi;\n"
            "• onboarding va xizmat ko'rsatishni Janob HR jamoasi bajaradi;\n"
            "• mijoz tarif olsa, agentlikka komissiya yoziladi.\n\n"
            "Shunday qilib bitta mijozdan faqat marketing emas, qo'shimcha HR yechimi orqali ham daromad qilish imkoniyati paydo bo'ladi."
        )

    if role == "blogger":
        if q1 == "business" or q2 == "many":
            audience = "Auditoriyangizda biznes egalari ko'p — bu Janob HR uchun eng mos auditoriyalardan biri."
        elif q1 == "mixed" or q2 == "some":
            audience = "Auditoriyangiz aralash, lekin uning ichida biznes yuritadigan segment bor. Janob HR'ni aynan shu segmentga taklif qilish mumkin."
        else:
            audience = "Biznes auditoriyangiz katta bo'lmasa ham, tavsiyani faqat biznes yuritadigan kuzatuvchilarga yo'naltirish mumkin."

        if q3 == "ads":
            income = "Hozir daromadingiz reklama buyurtmalariga bog'liq; reklama tushmagan davrda auditoriya daromad keltirmaydi."
        elif q3 == "own":
            income = "Siz auditoriyangizni o'z mahsulotingiz orqali allaqachon monetizatsiya qilyapsiz. Janob HR asosiy mahsulotingizga tegmasdan qo'shimcha taklif bo'la oladi."
        elif q3 == "both":
            income = "Siz auditoriyani bir nechta usulda monetizatsiya qilasiz; Janob HR uchinchi, natijaga bog'liq daromad kanaliga aylanishi mumkin."
        else:
            income = "Hozir auditoriyadan muntazam daromad qilmayapsiz; referral model mahsulot yaratmasdan monetizatsiyani boshlash imkonini beradi."

        return (
            f"🧩 <b>Blogingiz uchun imkoniyat</b>\n\n{audience}\n{income}\n\n"
            "<b>Janob HR sizga qanday yordam beradi?</b>\n"
            "• siz o'z auditoriyangizga bizneslar uchun foydali HR yechimini tavsiya qilasiz;\n"
            "• sizga shaxsiy referral link va tayyor reklama matnlari beriladi;\n"
            "• mahsulot, onboarding va mijoz bilan ishlashni biz bajaramiz;\n"
            "• referral orqali kelgan mijoz tarif olsa, siz komissiya olasiz.\n\n"
            "Ya'ni faqat yangi reklama buyurtmasini kutish emas, mavjud auditoriyadan qo'shimcha daromad olish imkoniyati paydo bo'ladi."
        )

    # other
    if q1 in {"work", "friends", "often"} and q2 in {"active", "small"}:
        channel = "Sizda ikkita kuchli kanal bor: biznes egalari bilan shaxsiy aloqa va ijtimoiy tarmoq auditoriyasi."
    elif q1 in {"work", "friends", "often"}:
        channel = "Sizda biznes egalari bilan to'g'ridan-to'g'ri aloqa bor — referral tavsiya uchun shu yetarli boshlang'ich kanal."
    elif q2 in {"active", "small"}:
        channel = "Bizneslar bilan shaxsiy aloqangiz kam bo'lsa ham, auditoriyangiz orqali kerakli segmentga chiqishingiz mumkin."
    else:
        channel = "Hozir biznes aloqasi va auditoriya kuchli emas. Shuning uchun sizga tayyor referral link va sotuv materiali bilan asta-sekin boshlash modeli mosroq."

    return (
        f"🧩 <b>Sizning holatingiz</b>\n\n{channel}\n\n"
        "<b>Janob HR sizga qanday yordam beradi?</b>\n"
        "• biznesga tayyor HR yechimini tavsiya qilasiz;\n"
        "• siz uchun alohida referral link beriladi;\n"
        "• mahsulotni tushuntirish, onboarding va xizmatni biz bajaramiz;\n"
        "• mijoz tarif sotib olsa, sizga komissiya hisoblanadi.\n\n"
        "Siz HR mutaxassisi bo'lishingiz yoki alohida xizmat yaratishingiz shart emas."
    )


def derive_partner_db_fields(data: dict) -> tuple[bool, str]:
    role = data.get("role")
    q1 = data.get("q1")
    q2 = data.get("q2")

    if role in {"targetolog", "smm", "agency"}:
        band = q1 if q1 in {"0", "1-3", "4-10", "10+"} else "0"
        return band != "0", band
    if role == "blogger":
        has_clients = q1 == "business" or q2 in {"many", "some"}
        return has_clients, "audience"
    has_clients = q1 in {"work", "friends", "often"}
    return has_clients, "network" if has_clients else "0"


async def send_phone_step(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer(build_diagnosis(data))
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Agar shu model sizga mos bo'lsa, arizani yakunlaymiz. Tasdiqlangach sizga referral link, tayyor sotuv matnlari va statistika ochiladi.\n\n"
        "Bog'lanish uchun telefon raqamingizni yuboring.",
        reply_markup=kb,
    )
    await state.set_state(PartnerForm.phone)


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
        await message.answer("👔 Janob HR referral qabul qilindi. Setup bot manzili hali sozlanmagan.")
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
            await message.answer("⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach bot sizga shaxsiy referral link beradi.")
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
        "🤝 <b>Janob HR hamkorlik dasturi</b>\n\n"
        "Sizga mos hamkorlik modelini topish uchun avval kasbingiz va hozirgi imkoniyatlaringizni bilib olamiz.\n\n"
        "Javoblaringizga qarab bot sizga Janob HR aynan qanday yordam berishi va qayerdan qo'shimcha daromad olish mumkinligini ko'rsatadi.\n\n"
        "<b>Siz kimsiz?</b>",
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
    text, options = question_1(role)
    await callback.message.edit_text(
        f"Tanlandi: <b>{ROLE_LABELS[role]}</b>\n\n{text}",
        reply_markup=options_keyboard("q1", options),
    )
    await state.set_state(PartnerForm.q1)
    await callback.answer()


@router.callback_query(PartnerForm.q1, F.data.startswith("q1:"))
async def answer_q1(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(q1=callback.data.split(":", 1)[1])
    data = await state.get_data()
    text, options = question_2(data["role"])
    await callback.message.edit_text(text, reply_markup=options_keyboard("q2", options))
    await state.set_state(PartnerForm.q2)
    await callback.answer()


@router.callback_query(PartnerForm.q2, F.data.startswith("q2:"))
async def answer_q2(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(q2=callback.data.split(":", 1)[1])
    data = await state.get_data()
    text, options = question_3(data["role"])
    await callback.message.edit_text(text, reply_markup=options_keyboard("q3", options))
    await state.set_state(PartnerForm.q3)
    await callback.answer()


@router.callback_query(PartnerForm.q3, F.data.startswith("q3:"))
async def answer_q3(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(q3=callback.data.split(":", 1)[1])
    data = await state.get_data()
    if data["role"] == "blogger":
        text, options = question_4(data["role"])
        await callback.message.edit_text(text, reply_markup=options_keyboard("q4", options))
        await state.set_state(PartnerForm.q4)
    else:
        await callback.message.edit_reply_markup(reply_markup=None)
        await send_phone_step(callback.message, state)
    await callback.answer()


@router.callback_query(PartnerForm.q4, F.data.startswith("q4:"))
async def answer_q4(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(q4=callback.data.split(":", 1)[1])
    await callback.message.edit_reply_markup(reply_markup=None)
    await send_phone_step(callback.message, state)
    await callback.answer()


@router.message(PartnerForm.phone, F.contact)
async def receive_phone(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    has_clients, client_band = derive_partner_db_fields(data)
    partner = await pdb.upsert_application(
        user_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username or "",
        phone=message.contact.phone_number,
        role=data["role"],
        has_business_clients=has_clients,
        client_band=client_band,
    )
    await state.clear()
    await message.answer(
        "✅ Arizangiz yuborildi.\n\n"
        "Tasdiqlangach sizga tayyor tizim ochiladi: referral link → mijoz Janob HR'ni sinaydi → "
        "tarif sotib olsa komissiya sizga yoziladi.\n\n"
        "Siz mahsulot yaratmaysiz va mijozga HR xizmatini o'zingiz ko'rsatishingiz shart emas.",
        reply_markup=ReplyKeyboardRemove(),
    )

    answers = f"Q1: {data.get('q1', '—')} | Q2: {data.get('q2', '—')} | Q3: {data.get('q3', '—')}"
    if data.get("q4"):
        answers += f" | Q4: {data['q4']}"
    notice = (
        "🤝 <b>Yangi partner arizasi</b>\n\n"
        f"#{partner['id']} — {partner['full_name']}\n"
        f"Rol: {ROLE_LABELS.get(partner['role'], partner['role'])}\n"
        f"Profil javoblari: {answers}\n"
        f"Biznes aloqasi: {'Ha' if partner['has_business_clients'] else 'Yo‘q'}\n"
        f"Segment: {partner['client_band']}\n"
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
