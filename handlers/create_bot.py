"""
Janob HR — "O'z HR botingizni yarating" bo'limi.

YANGI STRATEGIYA (konsultativ sotuv): qattiq belgilangan savollar o'rniga —
avval kuchli hikoya + taqdimot bilan muammoni "his qildiramiz", keyin AI
orqali MOSLASHUVCHAN suhbat olib boramiz (mijozning har bir javobiga qarab
keyingi savol o'zgaradi). Faqat shundan keyin — ro'yxatdan o'tish (2 ta bot)
va DARHOL sinov rejimida (5 ta arizagacha bepul) ishga tushirish.
"""
import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import FSInputFile, Message

from services import database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="create_bot")

TRIAL_APPLICATION_LIMIT = 5
_AI_CONVERSATION_TURNS = 4  # Diagnostika -> Muammo -> Eskalatsiya -> Vizualizatsiya
_PRESENTATION_PATH = "assets/janobHR_taqdimot.pptx"

_OPENING_STORY = (
    "🤔 Kichik bir hikoya aytib beray...\n\n"
    "Bir kompaniya 12 oy ichida 10 ta yangi xodim ishga oldi. Ammo deyarli har "
    "biri 1 oy ham to'liq ishlamasdan, ishdan ketib qolardi. Har safar yangi "
    "kelgan xodimni yana boshidan o'rgatish kerak bo'lardi — vaqt, kuch va pul "
    "sarflanardi.\n\n"
    "Shu orada, ular qo'lga kiritishi mumkin bo'lgan issiq mijozlar (lidlar) "
    "e'tiborsiz qolib, raqobatchilarga ketardi — chunki savdo bo'limida "
    "barqaror jamoa yo'q edi. Potensial mijozlar shunchaki yo'qolib borardi.\n\n"
    "Bu — ko'plab kompaniyalarda jim ichida takrorlanadigan holat.\n\n"
    "Aytingchi — sizning kompaniyangizda kadrlar bilan bog'liq ENG KATTA "
    "muammo nima?"
)


class CreateBotForm(StatesGroup):
    in_ai_conversation = State()
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

    try:
        await message.answer_document(
            FSInputFile(_PRESENTATION_PATH),
            caption="📊 Avval, Janob HR haqida qisqa taqdimot:",
        )
    except Exception:
        logger.exception("Taqdimotni yuborib bo'lmadi — matn bilan davom etamiz.")

    await message.answer(_OPENING_STORY)
    await state.update_data(ai_history=[], ai_turn_count=0)
    await state.set_state(CreateBotForm.in_ai_conversation)


async def _start_signup(message: Message, state: FSMContext):
    await message.answer(
        "Aynan shu — Janob HR. AI orqali nomzodlarni inson omilisiz, aniq "
        "mezonlar bo'yicha saralaydi, sizga faqat tayyor, mos nomzodlarni "
        "qoldiradi."
    )
    await message.answer(
        f"🎁 Buni o'zingiz ko'rish uchun — birinchi <b>{TRIAL_APPLICATION_LIMIT} ta "
        "ariza</b> SIZGA BUTUNLAY BEPUL. Hech qanday to'lov qilmasdan, o'z "
        "haqiqiy vakansiyangiz bilan sinab ko'rasiz."
    )
    await message.answer(
        "Endi sozlashni boshlaymiz. Sizga IKKITA bot kerak bo'ladi:\n"
        "1️⃣ Nomzodlar ariza topshiradigan bot\n"
        "2️⃣ Faqat sizning o'zingiz (va xodimlaringiz) ishlatadigan Admin panel-bot\n\n"
        "Avval, kompaniyangiz nomini yozing:"
    )
    await state.set_state(CreateBotForm.waiting_company_name)


@router.message(CreateBotForm.in_ai_conversation, F.text)
async def continue_ai_conversation(message: Message, state: FSMContext):
    from services.sales_conversation import get_next_message

    data = await state.get_data()
    history = data.get("ai_history", [])
    history.append({"role": "user", "content": message.text.strip()})
    turn_count = data.get("ai_turn_count", 0) + 1

    reply = await get_next_message(history, current_step=turn_count)

    if reply is None:
        # AI hech qanday provayderdan javob bermasa - xavfsiz zaxira:
        # suhbatni to'xtatib, darhol royxatdan otishga otamiz.
        logger.warning("Sotuv suhbati uchun AI javob bermadi - royxatdan otishga otamiz.")
        await message.answer(
            "Tushunarli! Aytganlaringiz — aynan Janob HR yordam beradigan muammo."
        )
        await state.update_data(ai_history=history, ai_turn_count=turn_count)
        await _start_signup(message, state)
        return

    history.append({"role": "assistant", "content": reply})
    await state.update_data(ai_history=history, ai_turn_count=turn_count)
    await message.answer(reply)

    if turn_count >= _AI_CONVERSATION_TURNS:
        await _start_signup(message, state)


@router.message(CreateBotForm.in_ai_conversation)
async def wrong_type_in_conversation(message: Message, state: FSMContext):
    await message.answer("Iltimos, javobingizni oddiy matn ko'rinishida yozing.")


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
    await state.clear()

    logger.info(
        "Yangi SINOV mijozi: id=%s, kompaniya=%s, nomzod-bot=@%s, admin-bot=@%s",
        tenant_id, data["company_name"], result["candidate_username"], result["admin_username"],
    )

    notice = (
        f"🆕 <b>Yangi SINOV mijozi!</b>\n\n"
        f"№{tenant_id} — {data['company_name']}\n"
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
