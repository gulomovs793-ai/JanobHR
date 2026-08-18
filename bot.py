"""
Janob HR — B2B HR Assistant Telegram Bot
Ishga tushirish: python bot.py  (avval .env faylini sozlang, requirements.txt o'rnating)
"""
import asyncio
import logging
import os
import ssl

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from services.database import init_db
from handlers import start, vacancy, questions, files, admin, sell

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("janob_hr_bot")


def _build_session():
    """
    Ba'zi muhitlarda (masalan korporativ proksi yoki sandbox) chiquvchi HTTPS
    trafik maxsus (o'z-o'ziga imzolangan) sertifikat orqali o'tadi. Bunday holda
    SSL_CERT_FILE / REQUESTS_CA_BUNDLE / CURL_CA_BUNDLE env o'zgaruvchisi
    ko'rsatilgan bo'ladi — shu holatda uni aiohttp'ning ishonchli sertifikatlar
    ro'yxatiga qo'shamiz. Oddiy server (Render/VPS)da bu o'zgaruvchilar
    sozlanmagan bo'ladi, shuning uchun bu funksiya shunchaki None qaytaradi va
    aiogram standart sozlamalar bilan ishlayveradi.
    """
    extra_ca = (
        os.getenv("SSL_CERT_FILE") or os.getenv("REQUESTS_CA_BUNDLE") or os.getenv("CURL_CA_BUNDLE")
    )
    if not extra_ca or not os.path.exists(extra_ca):
        return None
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=extra_ca)
    logger.info("Qo'shimcha CA sertifikat yuklandi: %s", extra_ca)
    session = AiohttpSession()
    # aiogram ichki connector konfiguratsiyasini to'g'ridan-to'g'ri yangilaymiz
    # (aiogram bu yerga standart holda faqat certifi CA to'plamini beradi).
    session._connector_init["ssl"] = ctx
    return session


async def main():
    await init_db()

    bot = Bot(
        token=BOT_TOKEN,
        session=_build_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Handlerlar tartibi muhim: admin (callback) va start eng birinchi bo'lishi shart emas,
    # lekin har bir router o'z filtri (state/callback prefiksi) bilan ishlaydi.
    dp.include_router(admin.router)
    dp.include_router(sell.router)
    dp.include_router(start.router)
    dp.include_router(vacancy.router)
    dp.include_router(questions.router)
    dp.include_router(files.router)

    logger.info("Janob HR bot ishga tushdi ✅")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi.")
