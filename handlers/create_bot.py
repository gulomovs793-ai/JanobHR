"""
Janob HR — "O'z HR botingizni yarateng" bo'limi.

STRATEGIYA (2026-08-24 yangilandi — statik shablon savollar): AI orqali
MOSLASHUVCHAN suhbat (services/sales_conversation.py) 4 marta real testda
muvaffaqiyatsiz chiqdi — robotik takror, tavtologik savollar, noto'g'ri
talqin, "akademik" uslub. Har safar tuzatilgan, lekin har safar yangi
muammo chiqqan. Shuning uchun bu qismda endi ANIQ, OLDINDAN YOZILGAN 3 ta
shablon savolga o'tildi: ular hech qachon robotik/tavtologik/akademik
bo'la olmaydi, chunki ular AI tomonidan yaratilmaydi. AI-driven versiya
(services/sales_conversation.py) o'chirilmadi — kerak bo'lsa qaytarish
mumkin, lekin hozircha CHAQIRILMAYDI.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    FSInputFile, KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)

from services import database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="create_bot")

TRIAL_APPLICATION_LIMIT = 5
_PRESENTATION_PATH = "assets/janobHR_taqdimot.pptx"

_OPENING_MESSAGE = (
    "Har bir kompaniyada xodim yollashdagi asosiy muammo har xil bo'ladi: "
    "ba'zilarida mos nomzod topish, ba'zilarida saralashga ketadigan vaqt, "
    "boshqalarida esa ishga olingan xodimning uzoq ishlamasligi muammo bo'ladi."
)

# Foydalanuvchi (Shahriyor) tomonidan yozilgan 3 ta ANIQ savol — ketma-ket
# beriladi. Javoblar yig'ilgach, PROBLEM->CURRENT PROCESS->PAIN/IMPACT->
# PRODUCT FIT mantig'ida moslashtirilgan ko'prik xabar yaratiladi
# (generate_synthesis_pitch, faqat shu YAGONA joyda AI ishlatiladi).
_TEMPLATE_QUESTIONS = [
    "Hozir orzuyingizdagi xodim yollashda sizni eng ko'p qiynayotgan narsa nima?",
    "Odatda ishingizga qiziqqan nomzodlarni qanday saralaysiz?",
    "Qaysi muammoyingizni hal qilib bersak, Janob HR bilan muntazam ishlagan bo'lardingiz?",
]


class CreateBotForm(StatesGroup):
    in_ai_conversation = State()
    awaiting_interest = State()
    waiting_phone = State()
    waiting_full_name = State()
    waiting_company_name = State()
    waiting_candidate_token = State()
    waiting_admin_token = State()


_DECLINE_PATTERNS = [
    "yo'q", "kerak emas", "hozir emas", "hozircha yo'q", "keyinroq",
    "qiziqmayman", "bo'lmaydi", "shart emas",
]


def _looks_like_decline(text: str) -> bool:
    t = text.strip().lower()
    return any(p in t for p in _DECLINE_PATTERNS)


def _looks_like_phone(text: str) -> bool:
    digits = "".join(ch for ch in text if ch.isdigit())
    return 7 <= len(digits) <= 15


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

    try:
        await message.answer_document(
            FSInputFile(_PRESENTATION_PATH),
            caption="📊 Avval, Janob HR haqida qisqa taqdimot:",
        )
    except Exception:
        logger.exception("Taqdimotni yuborib bo'lmadi — matn bilan davom etamiz.")

    await message.answer(_OPENING_MESSAGE)
    await message.answer(_TEMPLATE_QUESTIONS[0])
    await state.update_data(ai_history=[{"role": "assistant", "content": _TEMPLATE_QUESTIONS[0]}], template_question_index=1)
    await state.set_state(CreateBotForm.in_ai_conversation)


async def _start_signup(message: Message, state: FSMContext):
    """Foydalanuvchi qiziqish bildirgandan (awaiting_interest) KEYIN chaqiriladi.
    Reklama-uslubidagi qayta pitch YO'Q — bu allaqachon sintez xabarida aytilgan
    edi. Faqat texnik sozlashga o'tish."""
    phone_keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Raqamimni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(
        "Unda boshlaymiz. Siz bilan bog'lanishimiz uchun pastdagi tugmani "
        "bosing — raqamingiz avtomatik yuboriladi:",
        reply_markup=phone_keyboard,
    )
    await state.set_state(CreateBotForm.waiting_phone)


@router.message(CreateBotForm.in_ai_conversation, F.text)
async def continue_ai_conversation(message: Message, state: FSMContext):
    from services.sales_conversation import generate_synthesis_pitch

    data = await state.get_data()
    history = data.get("ai_history", [])
    history.append({"role": "user", "content": message.text.strip()})
    question_index = data.get("template_question_index", 0)  # nechta savol berilgan

    if question_index < len(_TEMPLATE_QUESTIONS):
        next_question = _TEMPLATE_QUESTIONS[question_index]
        history.append({"role": "assistant", "content": next_question})
        question_index += 1
        await state.update_data(ai_history=history, template_question_index=question_index)
        await message.answer(next_question)
        return

    # Oxirgi (3-chi) savolga ham javob keldi — 3 ta javobni tahlil qilib,
    # 3 paragrafli DIAGNOSTIK XULOSA + YUMSHOQ CTA xabarini yaratamiz (YAGONA
    # AI chaqiruvi). Bu xabardan keyin DARHOL ro'yxatdan o'tishga O'TMAYMIZ —
    # foydalanuvchining qiziqish bildirishini KUTAMIZ (awaiting_interest).
    await state.update_data(ai_history=history)
    synthesis = await generate_synthesis_pitch(history)
    if synthesis:
        history.append({"role": "assistant", "content": synthesis})
        await state.update_data(ai_history=history)
        await message.answer(synthesis)
        await state.set_state(CreateBotForm.awaiting_interest)
    else:
        logger.warning("Tahlil xabari uchun AI javob bermadi — royxatdan otishga otamiz.")
        await _start_signup(message, state)


@router.message(CreateBotForm.awaiting_interest, F.text)
async def receive_interest_response(message: Message, state: FSMContext):
    if _looks_like_decline(message.text):
        await message.answer(
            "Tushunarli, bosim qilmayman. Xohlagan vaqtingizda /create_bot "
            "buyrug'i bilan qaytishingiz mumkin."
        )
        await state.clear()
        return

    await _start_signup(message, state)


@router.message(CreateBotForm.awaiting_interest)
async def wrong_type_in_interest(message: Message, state: FSMContext):
    await message.answer("Iltimos, javobingizni oddiy matn ko'rinishida yozing.")


@router.message(CreateBotForm.in_ai_conversation)
async def wrong_type_in_conversation(message: Message, state: FSMContext):
    await message.answer("Iltimos, javobingizni oddiy matn ko'rinishida yozing.")


@router.message(CreateBotForm.waiting_phone, F.contact)
async def receive_phone_contact(message: Message, state: FSMContext):
    # Telegramning o'z "kontakt ulashish" tugmasi orqali — eng aniq va tezkor yo'l.
    phone = message.contact.phone_number
    if not phone.startswith("+"):
        phone = "+" + phone
    await state.update_data(contact_phone=phone)
    await message.answer(
        "Endi ism va familyangizni to'liq yozing:", reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(CreateBotForm.waiting_full_name)


@router.message(CreateBotForm.waiting_phone, F.text)
async def receive_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    if not _looks_like_phone(phone):
        await message.answer(
            "Iltimos, tugmani bosing yoki raqamni to'g'ri kiriting (masalan: +998901234567)."
        )
        return

    await state.update_data(contact_phone=phone)
    await message.answer(
        "Endi ism va familyangizni to'liq yozing:", reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(CreateBotForm.waiting_full_name)


@router.message(CreateBotForm.waiting_phone)
async def wrong_phone_type(message: Message, state: FSMContext):
    await message.answer("Iltimos, tugmani bosing yoki raqamni oddiy matn ko'rinishida yuboring.")


@router.message(CreateBotForm.waiting_full_name, F.text)
async def receive_full_name(message: Message, state: FSMContext):
    full_name = message.text.strip()
    if len(full_name) < 3:
        await message.answer("Iltimos, ism va familyangizni to'liq kiriting.")
        return

    await state.update_data(contact_full_name=full_name)
    await message.answer("Kompaniyangiz nomini yozing:")
    await state.set_state(CreateBotForm.waiting_company_name)


@router.message(CreateBotForm.waiting_full_name)
async def wrong_full_name_type(message: Message, state: FSMContext):
    await message.answer("Iltimos, ism-familyangizni oddiy matn ko'rinishida yuboring.")


@router.message(CreateBotForm.waiting_company_name, F.text)
async def receive_company_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Iltimos, to'liq kompaniya nomini kiriting.")
        return

    await state.update_data(company_name=name)
    data = await state.get_data()

    # --- Lidni bazaga yozamiz (push-xabar EMAS — asoschi buni Admin
    # panelidagi "🎯 Lidlar" bo'limini ochganda ko'radi). Hatto mijoz
    # keyingi (texnik, token) bosqichida to'xtab qolsa ham, bu yerda
    # TO'LIQ kontakt ma'lumoti (telefon, ism-familya, kompaniya) saqlanadi. ---
    ai_history = data.get("ai_history", [])
    conversation_summary = "\n".join(
        f"  {'Mijoz' if m['role'] == 'user' else 'Bot'}: {m['content'][:150]}" for m in ai_history
    )
    try:
        lead_id = await database.create_lead(
            telegram_user_id=message.from_user.id,
            telegram_username=message.from_user.username or "",
            phone=data.get("contact_phone", ""),
            full_name=data.get("contact_full_name", ""),
            company_name=name,
            conversation_summary=conversation_summary,
        )
        await state.update_data(lead_id=lead_id)
    except Exception:
        logger.exception("Lidni bazaga yozib bo'lmadi.")

    await message.answer(
        "Rahmat! Endi sizga IKKITA bot kerak bo'ladi:\n"
        "1️⃣ Nomzodlar ariza topshiradigan bot\n"
        "2️⃣ Faqat sizning o'zingiz (va xodimlaringiz) ishlatadigan Admin panel-bot\n\n"
        "Avval, @BotFather orqali yaratgan <b>NOMZOD-BOT</b>ning TOKENINI yuboring.\n\n"
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
            contact_phone=data.get("contact_phone", ""),
            contact_full_name=data.get("contact_full_name", ""),
        )
    except Exception:
        logger.exception("Mijozni bazaga yozishda kutilmagan xato.")
        await wait_msg.edit_text("⚠️ Texnik xatolik yuz berdi. Iltimos, /create_bot bilan qayta urinib ko'ring.")
        return

    # --- Darhol SINOV rejimida faollashtiramiz - tolov hali sorалmaydi ---
    from services.tenant_activation import activate_tenant

    result = await activate_tenant(tenant_id, status="trial")
    if not result["ok"]:
        await wait_msg.edit_text(f"⚠️ {result['error']}")
        return

    await wait_msg.edit_text(
        f"✅ Ikkala botingiz ham tayyor va SINOV rejimida ishga tushdi:\n\n"
        f"1️⃣ Nomzod-bot: @{result['candidate_username']}\n"
        f"2️⃣ Admin panel-bot: @{result['admin_username']}\n\n"
        f"🎁 Birinchi <b>{TRIAL_APPLICATION_LIMIT} ta ariza</b> BEPUL. "
        "Bir necha soniyada ikkala bot ham ishlay boshlaydi — hoziroq sinab ko'rishingiz mumkin!\n\n"
        f"Buyurtma raqamingiz: <code>{tenant_id}</code>"
    )

    ai_history = data.get("ai_history", [])
    conversation_summary = "\n".join(
        f"  {'Mijoz' if m['role'] == 'user' else 'Bot'}: {m['content'][:150]}" for m in ai_history
    )

    lead_id = data.get("lead_id")
    if lead_id:
        try:
            await database.mark_lead_converted(lead_id, tenant_id)
        except Exception:
            logger.exception("Lid holatini 'mijozga aylandi'ga yangilab bo'lmadi.")

    await state.clear()

    logger.info(
        "Yangi SINOV mijozi: id=%s, kompaniya=%s, nomzod-bot=@%s, admin-bot=@%s",
        tenant_id, data["company_name"], result["candidate_username"], result["admin_username"],
    )

    notice = (
        f"🆕 <b>Yangi SINOV mijozi!</b>\n\n"
        f"№{tenant_id} — {data['company_name']}\n"
        f"Ism-familya: {data.get('contact_full_name', '-')}\n"
        f"Telefon: {data.get('contact_phone', '-')}\n"
        f"Nomzod-bot: @{result['candidate_username']}\n"
        f"Admin-bot: @{result['admin_username']}\n"
        f"Kim orqali: <code>{admin_id}</code>\n\n"
        f"💬 Sotuv suhbati:\n{conversation_summary or '(sahbat bo\u2019lmagan)'}"
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
