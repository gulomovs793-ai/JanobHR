"""
Janob HR Setup — yangi mijozlar o'zini ro'yxatdan o'tkazadigan alohida,
oddiy bot. Kompaniya nomi + o'z bot tokeni so'raladi, token avtomatik
tekshiriladi, mijoz "pending" holatda bazaga yoziladi.

MUHIM: bu bot to'lovni o'z ichiga OLMAYDI (ataylab chetlab o'tilgan).
Ro'yxatdan o'tgandan keyin, asoschi to'lovni qo'lda tekshirib, alohida
boshqaruv paneli orqali mijozni "faollashtiradi" — shundan keyin uning
o'z boti avtomatik ishga tushadi.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from config import FOUNDER_USER_ID, SETUP_BOT_TOKEN

logger = logging.getLogger("janob_hr_setup")

router = Router(name="setup")


class SetupForm(StatesGroup):
    waiting_company_name = State()
    waiting_token = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👔 <b>Janob HR</b> tizimiga xush kelibsiz!\n\n"
        "Bir necha daqiqada o'zingizning shaxsiy AI-HR botingizni sozlaymiz.\n\n"
        "Avval, kompaniyangiz nomini yozing:"
    )
    await state.set_state(SetupForm.waiting_company_name)


@router.message(SetupForm.waiting_company_name, F.text)
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
    await state.set_state(SetupForm.waiting_token)


@router.message(SetupForm.waiting_token, F.text)
async def receive_token(message: Message, state: FSMContext):
    from services import database  # aylanma import'dan qochish uchun shu yerda

    token = message.text.strip()

    existing = await database.get_tenant_by_token(token)
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

    tenant_id = await database.create_tenant(
        company_name=data["company_name"], bot_token=token, admin_user_ids=[admin_id],
    )

    await wait_msg.edit_text(
        f"✅ Tabriklaymiz! <b>@{me.username}</b> boti muvaffaqiyatli ro'yxatdan o'tkazildi.\n\n"
        f"Mijoz raqamingiz: <code>{tenant_id}</code>\n\n"
        "To'lovni amalga oshirgach, botingiz bir necha daqiqada avtomatik ishga tushadi — "
        "sizga shu yerda xabar beramiz."
    )
    await state.clear()

    logger.info(
        "Yangi mijoz ro'yxatdan o'tdi: id=%s, kompaniya=%s, bot=@%s",
        tenant_id, data["company_name"], me.username,
    )

    if FOUNDER_USER_ID:
        try:
            await message.bot.send_message(
                chat_id=FOUNDER_USER_ID,
                text=(
                    f"🆕 <b>Yangi mijoz ro'yxatdan o'tdi</b>\n\n"
                    f"№{tenant_id} — {data['company_name']}\n"
                    f"Bot: @{me.username}\n"
                    f"Admin Telegram ID: <code>{admin_id}</code>\n\n"
                    "To'lov tushgach, boshqaruv panelidan faollashtiring."
                ),
            )
        except Exception:
            logger.exception("Asoschiga bildirishnoma yuborib bo'lmadi.")


@router.message(SetupForm.waiting_token)
async def wrong_token_type(message: Message, state: FSMContext):
    await message.answer("Iltimos, tokenni oddiy matn ko'rinishida yuboring.")


async def main():
    bot = Bot(token=SETUP_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Janob HR Setup bot ishga tushdi ✅")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    asyncio.run(main())
