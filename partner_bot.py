"""Janob HR Partner Bot.

Maqsad:
- SMM/targetolog/agentlik/blogger hamkorlarga avval ularning muammosi va foydasini tushuntirish;
- founder tasdig'idan keyin referral link yoki promo kod berish;
- partnerga tayyor matnlar va statistikani ko'rsatish;
- biznes leadni hamkor botiga emas, asosiy Janob HR nomzod/biznes botiga uzatish.

Referral link uchun asosiy bot username'i:
1) JANOBHR_MAIN_BOT_USERNAME
2) PARTNER_REFERRAL_TARGET_USERNAME (orqaga moslik)
3) BOT_TOKEN orqali avtomatik getMe()
"""

import asyncio
import logging
import os
from html import escape

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
    MenuButtonWebApp,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    WebAppInfo,
)

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS, WEBHOOK_BASE_URL
from partner_payout_bot import payout_router, run_payout_reminders
from services import partner_database as pdb
from services.partner_ai import generate_partner_advice
from services.partner_links import build_referral_link, resolve_main_bot_username

logger = logging.getLogger("janob_hr_partner")
router = Router(name="partner")

PARTNER_BOT_TOKEN = os.getenv("PARTNER_BOT_TOKEN", "").strip()
WEBHOOK_BASE_URL = WEBHOOK_BASE_URL.rstrip("/")
_REFERRAL_TARGET_CACHE = ""

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
    "Mijoz sizning referral linkingiz yoki promo kodingiz orqali kelsa, to'lov tasdiqlangandan keyin komissiya yoziladi.\n\n"
    "🎟 Promo kod bersangiz, chegirma sizning bonus/komissiyangizdan ayriladi.\n"
    "Masalan, START tarifi 10% chegirma bilan sotilsa, chegirma shu tarif narxining 10 foizi bo'ladi. Chegirma miqdori komissiyangizdan ayriladi.\n\n"
    "💸 To'lovlar oyiga 3 marta beriladi: 1-sana, 11-sana va 21-sana. "
    "Agar tasdiqlangan komissiya belgilangan sanadan keyin 7 kungacha kechiksa, "
    "har bir kechikkan kun uchun 3 000 UZS qo'shimcha komissiya qo'shiladi. "
    "Yakshanba va rasmiy bayram kunlari kechikish kuniga kirmaydi."
)

FAQ_TEXT = (
    "❓ <b>Tez-tez so'raladigan savollar</b>\n\n"
    "<b>1. Hamkorlik qanday ishlaydi?</b>\n"
    "Siz Janob HR'ni biznes egalariga tavsiya qilasiz. Mijoz linkingiz yoki promo kodingiz orqali kelib tarif sotib olsa, siz o'sha sotuvdan komissiya olasiz.\n\n"
    "<b>2. Janob HR o'zi nima?</b>\n"
    "Janob HR — kompaniya vaqtini tejashga va to'g'ri xodim ishga olishga yordam beradigan tizim. U nomzodlarni Telegramda qabul qiladi, ularga savollar beradi, javoblarni AI bilan baholaydi va ish beruvchiga kuchli nomzodlarni ajratib beradi.\n\n"
    "<b>3. Mijozga qanday foydasi bor?</b>\n"
    "Saralashga kamroq vaqt ketadi, nomzodlar chatlarda yo'qolib qolmaydi, suhbatga kimni chaqirish kerakligi aniqroq bo'ladi.\n\n"
    "<b>4. Men mahsulotni sotamanmi?</b>\n"
    "Siz tavsiya qilasiz. Sizga tavsiya qilish uchun kerakli materiallar va tushuntirishlar beriladi.\n\n"
    "<b>5. Referral link nima?</b>\n"
    "Bu sizga biriktirilgan maxsus link. Mijoz shu link orqali kirsa, tizim uni siz olib kelgan mijoz sifatida eslab qoladi va tizimga kiritadi.\n\n"
    "<b>6. Promo kod nima?</b>\n"
    "Promo kod mijozga chegirma beradi. Tasdiqlangan hamkor Boshqaruv panelida foiz yoki aniq summa, qaysi tarifga tegishli ekanini va necha kun amal qilishini belgilaydi. 0%, 5%, 10%, 15% yoki 20% kabi qiymatlar tanlanadi; tizim tanlangan tarif komissiyasidan oshadigan chegirmani qabul qilmaydi. Bitta kod barcha tariflarda ishlasa, maksimal xavfsiz chegirma 25% yoki 99 000 UZS bo'ladi. Har bir hamkorda bitta faol promo kod bo'ladi.\n\n"
    "<b>7. Promo chegirma kim hisobidan beriladi?</b>\n"
    "Chegirma sizning komissiyangizdan ayriladi. Masalan, 30 000 UZS chegirma berilsa, START komissiyasi 99 000 - 30 000 = 69 000 UZS bo'ladi. Komissiya manfiy bo'lib qolmaydi.\n\n"
    "<b>8. Menga to'lanadigan komissiya qancha?</b>\n"
    "START — 99 000 UZS, GROWTH — 199 000 UZS, BUSINESS — 299 000 UZS. Promo ishlatilsa, chegirma shu summadan ayriladi.\n\n"
    "<b>9. Komissiya qachon balansimga tushirib beriladi?</b>\n"
    "Mijoz tarif sotib olib, to'lovi tasdiqlangandan keyin komissiya balansingizga yoziladi. Bepul sinov uchun komissiya berilmaydi, faqat tarif sotib olgan mijozlardan komissiya hisoblanadi.\n\n"
    "<b>10. Pulimni qachon yechib olsam bo'ladi?</b>\n"
    "Hamkor komissiyasini oyiga 3 marta yechib olish mumkin: <b>1-sana, 11-sana va 21-sana</b>. Shu sanalarda tasdiqlangan komissiyalar to'lab beriladi. Agar tasdiqlangan komissiya belgilangan sanadan keyin 7 kungacha kechiksa, har bir kechikkan kun uchun <b>3 000 UZS</b> qo'shimcha komissiya qo'shiladi. Yakshanba va rasmiy bayram kunlari kechikish kuniga kirmaydi.\n\n"
    "<b>11. 1, 11 yoki 21-sana yakshanba yoki bayram kuniga tushsa-chi?</b>\n"
    "To'lov keyingi ish kunida ko'rib chiqiladi. Yakshanba va rasmiy bayram kunlari kechikish hisobiga kirmaydi. Asosiysi, komissiya avval tasdiqlangan bo'lishi kerak.\n\n"
    "<b>12. Mijoz link orqali kirib, keyin promo kod ishlatsa nima bo'ladi?</b>\n"
    "Referral link mijozni sizga bog'laydi. Keyin o'zingiz yaratgan promo kod ishlatilsa, mijoz sizniki bo'lib qoladi va chegirma shu kod qoidasi bo'yicha hisoblanadi.\n\n"
    "<b>13. Mijoz boshqa hamkor promo kodini ishlatsa-chi?</b>\n"
    "Bunday holat alohida tekshiriladi. Mijoz avval qaysi hamkorga biriktirilgan bo'lsa, boshqa hamkor kodi avtomatik qabul qilinmaydi; komissiya ikki hamkorga bo'linmaydi. Zarur bo'lsa holat qo'lda ko'rib chiqiladi.\n\n"
    "<b>14. Komissiyani qanday qabul qilaman?</b>\n"
    "To'lov yechish vaqtida sizdan karta yoki kerakli to'lov ma'lumoti so'raladi. Ma'lumotlar to'g'ri bo'lishi kerak. To'lov qilingandan keyin siz taqdim qilgan Telegram username'ga chek yuboriladi, agar spam yoki aloqa bo'yicha muammo bo'lmasa.\n\n"
    "<b>15. Hamkor bo'lsam daromad kafolatlanadimi?</b>\n"
    "Komissiya faqat real mijoz kelib, tarif sotib olganda beriladi. Biz sizga referral link, promo kod va tayyor xabar matnlarini beramiz.\n\n"
    "<b>16. Savolimga javob ola olmagan bo'lsam nima qilish kerak?</b>\n"
    "Savolingizni shu yerga yozing, imkon qadar javob beramiz."
)


class PartnerForm(StatesGroup):
    role = State()
    q1 = State()
    q2 = State()
    q3 = State()
    q4 = State()
    phone = State()

class PartnerSupportForm(StatesGroup):
    waiting_question = State()



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


def partner_miniapp_url() -> str:
    return f"{WEBHOOK_BASE_URL}/partner" if WEBHOOK_BASE_URL else ""


def main_menu() -> ReplyKeyboardRemove:
    """Reply menyuni yashiradi; faqat ko'k Mini App tugmasi qoladi."""
    return ReplyKeyboardRemove()


def founder_review_keyboard(partner_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Tasdiqlash", callback_data=f"fp:partnerapprove:{partner_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish", callback_data=f"fp:partnerreject:{partner_id}"
                ),
            ]
        ]
    )


def promo_discount_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="0% — chegirmasiz", callback_data="promo:0")],
            [InlineKeyboardButton(text="5%", callback_data="promo:5")],
            [InlineKeyboardButton(text="10%", callback_data="promo:10")],
            [InlineKeyboardButton(text="15%", callback_data="promo:15")],
            [InlineKeyboardButton(text="20%", callback_data="promo:20")],
        ]
    )


async def _safe_bot_username(bot: Bot | None) -> str:
    if bot is None:
        return ""
    try:
        me = await bot.get_me()
        return (me.username or "").strip().lstrip("@")
    except Exception:
        logger.exception("Bot username aniqlanmadi")
        return ""


async def referral_target_username(current_bot: Bot | None = None) -> str | None:
    """Mijoz kiradigan ASOSIY bot username'ini qaytaradi.

    Eng muhim himoya: target hech qachon partner botning o'zi bo'lmasligi kerak.
    Aks holda referral link yana hamkor botga qaytib qoladi.
    """
    global _REFERRAL_TARGET_CACHE
    if _REFERRAL_TARGET_CACHE:
        return _REFERRAL_TARGET_CACHE

    partner_username = await _safe_bot_username(current_bot)
    username = await resolve_main_bot_username(
        current_partner_username=partner_username
    )
    if username:
        _REFERRAL_TARGET_CACHE = username
    return username


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


def fallback_diagnosis(data: dict) -> str:
    role = data.get("role", "other")
    q1, q2 = data.get("q1"), data.get("q2")

    if role in {"targetolog", "smm"}:
        if q1 == "0":
            return (
                "Hozir sizda faol biznes mijoz ko'p emas. Shuning uchun sizga katta va'da bermaymiz. "
                "Lekin sizga tayyor referral link va xabar matnlari beramiz. Tanish bizneslarga yoki keyingi mijozlarga Janob HR'ni tavsiya qilishingiz mumkin. Mijoz tarif olsa, sizga komissiya yoziladi."
            )
        if q2 in {"often", "sometimes"}:
            return (
                "Siz bizneslar bilan ishlaysiz va ularda xodim qidirish muammosi chiqishini ko'rasiz. "
                "Lekin hozir bu muammo sizga pul olib kelmayapti. Janob HR orqali siz ularga tayyor HR botni tavsiya qilasiz. Nomzodlarni qabul qilish, savol berish va AI saralashni tizim qiladi. Mijoz tarif olsa, siz komissiya olasiz."
            )
        return (
            "Sizning kuchingiz — biznes egalari bilan aloqa. Ularda xodim qidirish muammosi paydo bo'lsa, siz Janob HR'ni tavsiya qila olasiz. Mijoz tarif olsa, sizga komissiya yoziladi."
        )

    if role == "agency":
        if q2 == "yes":
            return (
                "Siz allaqachon biznes mijozlar va HR muammolari bilan ishlaysiz. Janob HR sizdagi qo'lda saralash ishini yengillashtiradi: nomzodlarni qabul qiladi, savol beradi va kuchlilarini ajratadi. Siz mijozga qo'shimcha xizmat sifatida tavsiya qilasiz, tarif olinsa komissiya sizga yoziladi."
            )
        return (
            "Agentligingizda biznes mijozlar bo'lsa, ularning xodim topish muammosi ham vaqti-vaqti bilan chiqadi. Lekin bu xizmat sizda bo'lmasa, pul imkoniyati o'tib ketadi. Janob HR'ni tavsiya qilasiz, mijoz tarif olsa komissiya sizga yoziladi."
        )

    if role == "blogger":
        if data.get("q3") == "ads":
            return (
                "Sizda auditoriya bor, lekin reklama har kuni tushmaydi. Janob HR orqali biznes egalari uchun foydali narsani tavsiya qilasiz. Mijoz sizning link yoki promo kodingiz orqali tarif olsa, siz komissiya olasiz."
            )
        return (
            "Auditoriyangiz ichida biznes qiladigan odamlar bo'lsa, Janob HR ularga aniq foyda beradi: nomzodlarni tartibli qabul qiladi va AI bilan saralaydi. Siz faqat tavsiya qilasiz, mijoz tarif olsa komissiya olasiz."
        )

    if q1 in {"work", "friends", "often"} or q2 in {"active", "small"}:
        return (
            "Sizda biznes egalariga chiqish yo'li bor. Janob HR sizga shu aloqani daromadga aylantirish imkonini beradi: siz tavsiya qilasiz, mijoz tarif olsa sizga komissiya yoziladi."
        )
    return (
        "Hozir sizda biznes aloqasi ham, auditoriya ham kuchli emas. Shuning uchun sizga bosim qilmaymiz. Tasdiqlansangiz, tayyor referral link va xabar matnlari beriladi. Avval tanish bizneslar orqali sekin sinab ko'rishingiz mumkin."
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
    ai_advice = await generate_partner_advice(data)
    advice = ai_advice or fallback_diagnosis(data)
    await message.answer(f"🧠 <b>Sizga mos javob</b>\n\n{advice}")

    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Shu model sizga mos bo'lsa, arizani yakunlaymiz. Tasdiqlangach sizga 2 xil yo'l ochiladi:\n\n"
        "1️⃣ shaxsiy referral link\n"
        "2️⃣ mijozga chegirma beradigan promo kod\n\n"
        "Bog'lanish uchun telefon raqamingizni yuboring.",
        reply_markup=kb,
    )
    await state.set_state(PartnerForm.phone)


async def send_partner_home(message: Message, partner: dict) -> None:
    await message.answer(
        "🤝 <b>Janob HR Hamkor</b>\n\n"
        "Profilingiz faol. Ko'k <b>«Boshqaruv paneli»</b> tugmasini bosing — referral, leadlar, promo, komissiya va pul yechish bitta panelda.\n\n"
        "Mijoz referral link yoki promo orqali tarif sotib olib, to'lovi tasdiqlanganda komissiya balansingizga yoziladi.",
        reply_markup=main_menu(),
    )


async def handle_referral_entry(message: Message, code: str) -> bool:
    """Eski partner-bot r_CODE linklari uchun fallback: mijozni asosiy botga uzatadi."""
    partner = await pdb.get_partner_by_code(code.upper())
    if not partner:
        return False

    await pdb.record_referral_click(partner["id"], message.from_user.id)
    target_username = await referral_target_username(message.bot)

    if target_username:
        target_url = build_referral_link(target_username, partner.get("referral_code"))
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="👔 Davom etish", url=target_url)]
            ]
        )
        await message.answer(
            ""
            "Davom etish uchun pastdagi tugmani bosing.",
            reply_markup=kb,
        )
    else:
        await message.answer(
            "⚠️ Referral linkni hozir ochib bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
    return True


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, bot: Bot) -> None:
    args = (message.text or "").split(maxsplit=1)
    if (
        len(args) == 2
        and args[1].startswith("r_")
        and await handle_referral_entry(message, args[1][2:])
    ):
        return

    await state.clear()
    partner = await pdb.get_partner_by_user_id(message.from_user.id)
    if partner:
        if partner["status"] == "approved":
            await send_partner_home(message, partner)
            return
        if partner["status"] == "pending":
            await message.answer("⏳ Arizangiz ko'rib chiqilmoqda. Tasdiqlangach referral link, promo kod va FAQ bo'limi ochiladi.")
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
        "Avval sizni tushunib olamiz. Keyin sizga oddiy tilda Janob HR qanday yordam berishi va qanday daromad qilish mumkinligini ko'rsatamiz.\n\n"
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
        "Tasdiqlangach sizga referral link, promo kod va tez-tez so'raladigan savollar bo'limi ochiladi.\n\n"
        "Mijoz link yoki promo kod orqali tarif sotib olsa, komissiya sizga yoziladi.",
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
    if not FOUNDER_BOT_TOKEN:
        logger.error("Partner arizasi yuborilmadi: FOUNDER_BOT_TOKEN sozlanmagan.")
        return
    founder_bot = Bot(
        token=FOUNDER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        for founder_id in FOUNDER_USER_IDS:
            try:
                await founder_bot.send_message(
                    founder_id,
                    notice,
                    reply_markup=founder_review_keyboard(partner["id"]),
                )
            except Exception:
                logger.exception(
                    "Founder Botga partner arizasini yuborib bo'lmadi: %s", founder_id
                )
    finally:
        await founder_bot.session.close()


@router.message(PartnerForm.phone)
async def wrong_phone(message: Message) -> None:
    await message.answer("Pastdagi «📱 Telefon raqamni yuborish» tugmasini bosing.")


@router.callback_query(F.data.startswith("partner_approve:"))
async def approve_partner(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 2 or parts[0] != "partner_approve" or not parts[1].isdecimal():
        await callback.answer("Noto'g'ri partner so'rovi.", show_alert=True)
        return
    partner_id = int(parts[1])
    if partner_id <= 0:
        await callback.answer("Noto'g'ri partner so'rovi.", show_alert=True)
        return
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
            "Ko'k <b>«Boshqaruv paneli»</b> tugmasi yoqildi. Referral link, leadlar, promo kod, komissiya, pul yechish va FAQ bo'limlari bir joyda ishlaydi.\n\n"
            "Mijoz tarif sotib olib, to'lovi tasdiqlanganda komissiya balansingizga yoziladi.",
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
    parts = (callback.data or "").split(":")
    if len(parts) != 2 or parts[0] != "partner_reject" or not parts[1].isdecimal():
        await callback.answer("Noto'g'ri partner so'rovi.", show_alert=True)
        return
    partner_id = int(parts[1])
    if partner_id <= 0:
        await callback.answer("Noto'g'ri partner so'rovi.", show_alert=True)
        return
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
        await message.answer("Bu bo'lim faqat tasdiqlangan hamkorlar uchun. /start yuboring.")
        return None
    return partner


@router.message(F.text == "📱 Hamkor paneli")
async def partner_panel_fallback(message: Message) -> None:
    if not await require_approved(message):
        return
    url = partner_miniapp_url()
    if not url:
        await message.answer(
            "⚠️ Boshqaruv panelini hozir ochib bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
        return
    await message.answer(
        "📱 <b>Hamkor boshqaruv paneli</b>\n\n"
        "Shaxsiy referral, leadlar, promo va komissiya ma'lumotlaringizni oching.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📱 Panelni ochish", web_app=WebAppInfo(url=url))]
            ]
        ),
    )


@router.message(F.text.in_({"🔗 Referral link", "🔗 Mening referral linkim"}))
async def my_link(message: Message, bot: Bot) -> None:
    partner = await require_approved(message)
    if not partner:
        return
    target_username = await referral_target_username(bot)
    if not target_username:
        await message.answer(
            ""
            "⚠️ Referral linkni hozir yaratib bo'lmadi. Birozdan keyin qayta urinib ko'ring."
        )
        return
    link = build_referral_link(target_username, partner.get("referral_code"))
    await message.answer(
        "🔗 <b>Sizning referral linkingiz</b>\n\n"
        f"<code>{link}</code>\n\n"
        "Mijozga shu linkni yuboring.\n"
        "Link orqali kelgan mijoz sizga avtomatik biriktiriladi."
    )


@router.message(F.text == "🎟 Promo kod")
async def promo_section(message: Message) -> None:
    partner = await require_approved(message)
    if not partner:
        return
    await message.answer(
        "🎟 <b>Promo kod</b>\n\n"
        "Boshqaruv panelida o'zingizga promo kod yarating: chegirmani foizda yoki aniq summada belgilang va amal qilish kunini tanlang.\n\n"
        "Chegirma sizning komissiyangizdan ayriladi. Yangi kod yaratilsa, avvalgi faol kod yopiladi.",
    )


@router.callback_query(F.data.startswith("promo:"))
async def choose_promo(callback: CallbackQuery) -> None:
    partner = await pdb.get_partner_by_user_id(callback.from_user.id)
    if not partner or partner["status"] != "approved":
        await callback.answer("Bu bo'lim faqat tasdiqlangan hamkorlar uchun.", show_alert=True)
        return
    try:
        percent = int(callback.data.split(":", 1)[1])
        promo = await pdb.create_or_update_promo_code(partner["id"], percent)
    except Exception:
        logger.exception("Promo kod yaratishda xato")
        await callback.answer("Promo kod yaratishda xato yuz berdi.", show_alert=True)
        return
    if not promo:
        await callback.answer("Promo kod yaratilmadi.", show_alert=True)
        return

    start = pdb.calculate_partner_payout("start", percent)
    growth = pdb.calculate_partner_payout("growth", percent)
    business = pdb.calculate_partner_payout("business", percent)
    lines = [
        "🎟 <b>Promo kodingiz tayyor</b>",
        "",
        f"Kod: <code>{promo['code']}</code>",
        f"Chegirma: <b>{percent}%</b>",
        "",
        "Mijozga shunday yozishingiz mumkin:",
        f"<code>Mening promo kodim: {promo['code']} — Janob HR tarifiga {percent}% chegirma beradi.</code>",
        "",
        "<b>Hisob-kitob:</b>",
        f"START: mijoz {pdb.format_uzs(start['discounted_base_amount'])} to'laydi, siz {pdb.format_uzs(start['commission_amount'])} olasiz",
        f"GROWTH: mijoz {pdb.format_uzs(growth['discounted_base_amount'])} to'laydi, siz {pdb.format_uzs(growth['commission_amount'])} olasiz",
        f"BUSINESS: mijoz {pdb.format_uzs(business['discounted_base_amount'])} to'laydi, siz {pdb.format_uzs(business['commission_amount'])} olasiz",
    ]
    if percent:
        lines.append("\nChegirma sizning komissiyangizdan ayrildi. ")
    else:
        lines.append("\n0% tanlangani uchun mijoz chegirma olmaydi, siz to'liq komissiya olasiz.")
    await callback.message.edit_text("\n".join(lines))
    await callback.answer("Promo kod tayyor")


@router.message(F.text == "📊 Statistika")
async def statistics(message: Message) -> None:
    partner = await require_approved(message)
    if not partner:
        return
    stats = await pdb.get_partner_stats(partner["id"])
    await message.answer(
        "📊 <b>Hamkor statistikasi</b>\n\n"
        f"Referral kirishlar: <b>{stats['clicks']}</b>\n"
        f"Trial boshlaganlar: <b>{stats['trials']}</b>\n"
        f"Sotuvlar: <b>{stats['sales']}</b>\n"
        f"Promo buyurtmalar: <b>{stats['promo_orders']}</b>\n"
        f"Promo orqali sotuv: <b>{stats['promo_sales']}</b>\n"
        f"Hisoblangan komissiya: <b>{pdb.format_uzs(stats['earned'])}</b>"
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
        "<b>3. Promo bilan xabar</b>\n"
        "Janob HR tarifiga mening promo kodim bilan chegirma olishingiz mumkin. Kodni to'lov paytida kiriting — chegirma avtomatik hisoblanadi."
    )


def split_long_text(text: str, limit: int = 3500) -> list[str]:
    chunks: list[str] = []
    current = ""

    for block in text.split("\n\n"):
        piece = block if not current else "\n\n" + block
        if len(current) + len(piece) <= limit:
            current += piece
            continue
        if current:
            chunks.append(current)
        current = block

    if current:
        chunks.append(current)

    return chunks


@router.message(F.text.in_({"❓ Tez-tez so'raladigan savollar", "❓ Savollar va javoblar", "FAQ", "Faq"}))
async def faq_section(message: Message) -> None:
    if await require_approved(message):
        for chunk in split_long_text(FAQ_TEXT):
            await message.answer(chunk)


@router.message(F.text == "🆘 Yordam")
async def help_section(message: Message, state: FSMContext) -> None:
    partner = await require_approved(message)
    if not partner:
        return
    await state.set_state(PartnerSupportForm.waiting_question)
    await message.answer(
        "🆘 <b>Yordam</b>\n\n"
        "Savolingizni yozing. Javob shu chatga keladi.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Bekor qilish")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )


@router.message(PartnerSupportForm.waiting_question)
async def receive_support_question(message: Message, state: FSMContext) -> None:
    if message.text == "❌ Bekor qilish":
        await state.clear()
        await message.answer("Yordam bekor qilindi.", reply_markup=main_menu())
        return

    partner = await require_approved(message)
    if not partner:
        await state.clear()
        return

    question = (message.text or "").strip()
    if not question:
        await message.answer("Savolingizni matn ko'rinishida yozing.")
        return
    if len(question) > 3500:
        await message.answer("Savol juda uzun. Iltimos, 3500 belgidan qisqaroq yozing.")
        return

    try:
        ticket = await pdb.create_support_ticket(
            int(partner["id"]), message.from_user.id, question
        )
    except Exception:
        logger.exception("Support ticket yaratilmadi: partner_id=%s", partner.get("id"))
        await message.answer("Savolni yuborib bo'lmadi. Birozdan keyin qayta urinib ko'ring.")
        return

    await state.clear()
    await message.answer(
        f"✅ Savolingiz yuborildi.\n\n"
        f"Murojaat: <b>#{ticket['id']}</b>\n"
        "Javob shu chatga keladi.",
        reply_markup=main_menu(),
    )

    if not FOUNDER_BOT_TOKEN or not FOUNDER_USER_IDS:
        logger.error("Support ticket notification sozlanmagan: ticket_id=%s", ticket["id"])
        return

    founder_bot = Bot(
        token=FOUNDER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    username = str(partner.get("username") or "").strip().lstrip("@")
    username_line = f"@{escape(username)}" if username else "—"
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Javob berish", callback_data=f"fp:supportreply:{ticket['id']}")],
            [InlineKeyboardButton(text="📥 Mijozlarning savollari", callback_data="fp:support")],
        ]
    )
    notice = (
        f"💬 <b>Yangi savol #{ticket['id']}</b>\n\n"
        f"👤 {escape(str(partner.get('full_name') or 'Hamkor'))}\n"
        f"Telegram: {username_line}\n\n"
        f"<b>Savol:</b>\n{escape(question)}"
    )
    try:
        for founder_id in FOUNDER_USER_IDS:
            try:
                await founder_bot.send_message(founder_id, notice, reply_markup=markup)
            except Exception:
                logger.exception(
                    "Support ticket founderga yuborilmadi: ticket_id=%s founder_id=%s",
                    ticket["id"], founder_id,
                )
    finally:
        await founder_bot.session.close()



async def configure_partner_miniapp_menu(bot: Bot) -> None:
    url = partner_miniapp_url()
    if not url:
        return
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Boshqaruv paneli",
                web_app=WebAppInfo(url=url),
            )
        )
        logger.info("Partner Mini App menu tugmasi o'rnatildi: %s", url)
    except Exception:
        logger.exception("Partner Mini App menu tugmasi o'rnatilmadi")


async def main() -> None:
    if not PARTNER_BOT_TOKEN:
        raise RuntimeError("PARTNER_BOT_TOKEN sozlanmagan")
    await pdb.init_partner_db()
    bot = Bot(
        token=PARTNER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    target_username = await referral_target_username(bot)
    if target_username:
        logger.info("Partner referral target: @%s", target_username)
    else:
        logger.error("Partner referral target topilmadi")
    await configure_partner_miniapp_menu(bot)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    dp.include_router(payout_router)
    reminder_task = asyncio.create_task(run_payout_reminders(bot))
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Janob HR Partner Bot ishga tushdi")
    try:
        await dp.start_polling(bot)
    finally:
        reminder_task.cancel()
        await asyncio.gather(reminder_task, return_exceptions=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
