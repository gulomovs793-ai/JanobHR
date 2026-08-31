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

from config import (
    ADMIN_BOT_TOKEN,
    ADMIN_USER_IDS,
    BOT_TOKEN,
    SQLITE_PATH,
    WEBHOOK_BASE_URL,
)

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. .env faylini .env.example asosida yarating va "
        "BotFather'dan olingan tokenni kiriting."
    )
from handlers import (
    contact,
    create_bot,
    files,
    questions,
    resume_upfront,
    sell,
    start,
    vacancy,
)
from services import bot_registry
from services.database import init_db
from services.storage import SQLiteStorage
from services.tenant_middleware import TenantMiddleware

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
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
        os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
        or os.getenv("CURL_CA_BUNDLE")
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


def _build_candidate_bot(fsm_storage) -> tuple[Bot, Dispatcher]:
    bot = Bot(
        token=BOT_TOKEN,
        session=_build_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=fsm_storage)
    # Polling rejimida ham handlerlar `tenant_id`, `tenant` va `bot_role`
    # qiymatlarini kutadi. Webhook dispatcherida bo'lgani kabi har bir update'ga
    # ularni token orqali qo'shib beramiz.
    dp.update.outer_middleware(TenantMiddleware())

    # Handlerlar tartibi muhim emas — har bir router o'z filtri (state/callback
    # prefiksi) bilan ishlaydi. Qaror (qabul/rad) tugmalari endi Admin botda
    # ishlanadi (admin_bot/handlers_decisions.py), shuning uchun bu yerda yo'q.
    dp.include_router(sell.router)
    dp.include_router(create_bot.router)
    dp.include_router(start.router)
    dp.include_router(vacancy.router)
    dp.include_router(resume_upfront.router)
    dp.include_router(questions.router)
    dp.include_router(files.router)
    dp.include_router(contact.router)

    return bot, dp


def _build_admin_bot(fsm_storage) -> tuple[Bot, Dispatcher]:
    from admin_bot import (
        handlers_billing,
        handlers_candidates,
        handlers_decisions,
        handlers_export,
        handlers_interview,
        handlers_menu,
        handlers_vacancy_edit,
        handlers_vacancy_list,
    )
    from admin_bot.middleware import AdminOnlyMiddleware

    bot = Bot(
        token=ADMIN_BOT_TOKEN,
        session=_build_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=fsm_storage)
    dp.update.outer_middleware(TenantMiddleware())
    dp.update.outer_middleware(AdminOnlyMiddleware())

    dp.include_router(handlers_menu.router)
    dp.include_router(handlers_billing.router)
    dp.include_router(handlers_candidates.router)
    dp.include_router(handlers_vacancy_list.router)
    dp.include_router(handlers_vacancy_edit.router)
    dp.include_router(handlers_decisions.router)
    dp.include_router(handlers_interview.router)
    dp.include_router(handlers_export.router)

    return bot, dp


async def main():
    if WEBHOOK_BASE_URL:
        raise RuntimeError(
            "WEBHOOK_BASE_URL sozlangan: multi-tenant serverda python bot.py ni "
            "ishga tushirmang. Faqat python webhook_app.py ishlashi kerak. Aks holda "
            "bir token polling va webhookda parallel ishlaydi va Telegram flood-limit beradi."
        )

    await init_db()

    fsm_storage = SQLiteStorage(SQLITE_PATH)
    await fsm_storage.init()

    candidate_bot, candidate_dp = _build_candidate_bot(fsm_storage)
    bot_registry.candidate_bot = candidate_bot
    logger.info("Janob HR (nomzod) bot ishga tushdi ✅")
    await candidate_bot.delete_webhook(drop_pending_updates=True)
    polling_tasks = [candidate_dp.start_polling(candidate_bot)]
    from services.reminders import run_reminders_forever

    polling_tasks.append(run_reminders_forever())

    # Polling deploymentda to'lov kuzatuvchisi alohida process sifatida
    # ishga tushmaydi. Shu worker ichida parallel yoqamiz — aks holda bank
    # bildirishnomalarini faqat boshqa loyiha ko'rib, Janob HR tarifi yonmaydi.
    from userbot import is_userbot_configured, start_userbot

    if is_userbot_configured():
        logger.info("Janob HR to'lov kuzatuvchisi ishga tushmoqda ✅")
        polling_tasks.append(start_userbot())
    else:
        logger.warning(
            "To'lov kuzatuvchisi sozlanmagan — TELEGRAM_API_ID/HASH/USERBOT_SESSION ni tekshiring."
        )

    if ADMIN_BOT_TOKEN:
        if not ADMIN_USER_IDS:
            logger.warning(
                "ADMIN_BOT_TOKEN sozlangan, lekin ADMIN_USER_IDS bo'sh — hech kim admin "
                "botdan foydalana olmaydi va HECH QANDAY ANKETA HECH KIMGA YUBORILMAYDI. "
                ".env'da ADMIN_USER_IDS'ni to'ldiring."
            )
        admin_bot, admin_dp = _build_admin_bot(fsm_storage)
        bot_registry.admin_bot = admin_bot
        logger.info(
            "Janob HR Admin bot ishga tushdi ✅ (ruxsat etilgan adminlar: %d)",
            len(ADMIN_USER_IDS),
        )
        await admin_bot.delete_webhook(drop_pending_updates=True)
        polling_tasks.append(admin_dp.start_polling(admin_bot))
    else:
        logger.warning(
            "ADMIN_BOT_TOKEN sozlanmagan — Admin bot ishga tushirilmadi. Nomzod arizalari "
            "endi FAQAT Admin bot orqali yuboriladi, shuning uchun bu holatda HECH QANDAY "
            "ANKETA HECH KIMGA YUBORILMAYDI. ADMIN_BOT_TOKEN va ADMIN_USER_IDS'ni sozlang."
        )

    await asyncio.gather(*polling_tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot to'xtatildi.")
