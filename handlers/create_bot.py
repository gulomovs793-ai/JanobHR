"""
Janob HR — "O'z HR botingizni yarating" bo'limi.

Joriy botni sinab ko'rgan HAR QANDAY kishi shu bo'lim orqali o'ziga shu
tizimning nusxasini buyurtma qilishi mumkin. Avval 2-3 ta savol orqali
o'z muammosini "his qilishiga" yordam beramiz, keyin ikkita bot (nomzod +
admin) yaratamiz va DARHOL sinov rejimida (5 ta arizagacha bepul)
ishga tushiramiz — to'lov FAQAT sinov tugagandan keyin so'raladi.
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

TRIAL_APPLICATION_LIMIT = 5


class CreateBotForm(StatesGroup):
    waiting_q1_time = State()
    waiting_q2_cost = State()
    waiting_q3_frequency = State()
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
        "Avval, sizga aynan qanday foyda berishini aniqlash uchun 3 ta qisqa "
        "savol beraman — bu bir daqiqa vaqtingizni oladi."
    )
    await message.answer("1️⃣ Hozir yangi xodim topish uchun OYIGA qancha vaqt (soat) sarflaysiz?")
    await state.set_state(CreateBotForm.waiting_q1_time)


@router.message(CreateBotForm.waiting_q1_time, F.text)
async def receive_q1(message: Message, state: FSMContext):
    await state.update_data(answer_time=message.text.strip())
    await message.answer(
        "2️⃣ Oxirgi marta noto'g'ri odam yollaganingizda, bu sizga qanday zarar "
        "keltirdi? (vaqt, pul, yoki umuman esingizga tushmasa — \"yo'q\" deb yozing)"
    )
    await state.set_state(CreateBotForm.waiting_q2_cost)


@router.message(CreateBotForm.waiting_q2_cost, F.text)
async def receive_q2(message: Message, state: FSMContext):
    await state.update_data(answer_cost=message.text.strip())
    await message.answer("3️⃣ Oyiga o'rtacha necha marta yangi xodim qidirasiz?")
    await state.set_state(CreateBotForm.waiting_q3_frequency)


@router.message(CreateBotForm.waiting_q3_frequency, F.text)
async def receive_q3(message: Message, state: FSMContext):
    await state.update_data(answer_frequency=message.text.strip())

    await message.answer(
        "Rahmat! Aynan shu — vaqt va xato yollash xarajati — bizning tizim "
        "hal qiladigan muammo. AI orqali nomzodlarni avtomatik saralab, sizga "
        "faqat ENG MOS nomzodlarni qoldiradi.\n\n"
        "💡 Taqqoslash uchun: bitta noto'g'ri yollash — oylik maoshning "
        "15 barobarigacha zarar keltirishi mumkin (HR tadqiqotlariga ko'ra). "
        "Bizning xizmat esa buning ozgina qismini tashkil qiladi.\n\n"
        f"🎁 Shuning uchun — birinchi <b>{TRIAL_APPLICATION_LIMIT} ta ariza</b> "
        "SIZGA BUTUNLAY BEPUL. Hech qanday to'lov qilmasdan, o'z haqiqiy "
        "vakansiyangiz bilan sinab ko'rasiz."
    )
    await message.answer(
        "Endi sozlashni boshlaymiz. Sizga IKKITA bot kerak bo'ladi:\n"
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

    # --- Darhol SINOV rejimida faollashtiramiz - tolov hali sorالmaydi ---
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
        f"📋 Javoblari:\n"
        f"1) Oyiga sarflagan vaqti: {data.get('answer_time', '—')}\n"
        f"2) Notogri yollash zarari: {data.get('answer_cost', '—')}\n"
        f"3) Oyiga necha marta yollaydi: {data.get('answer_frequency', '—')}"
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
