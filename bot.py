"""
Janob HR — BITTA konsolidatsiyalangan xizmat.

Bu yerda BIR JARAYON ichida quyidagilar birga ishlaydi (bitta ma'lumotlar
bazasini baham ko'radi — bu MUHIM, chunki avval alohida xizmatlarga
bo'linganda ular bir-birining ma'lumotini ko'ra olmas edi):

1. Har bir FAOL mijozning ikkala boti (nomzod + admin) — POLLING orqali,
   dinamik ravishda kashf qilinadi (webhook SHART EMAS, kichik/o'rta
   miqyos uchun bu ancha sodda va ishonchli).
2. Userbot — bank to'lov bildirishnomalarini o'qib, mos mijozni avtomatik
   faollashtiruvchi tinglovchi (agar sozlangan bo'lsa).

Yangi mijoz "faollashtirilganda" (qo'lda yoki avtomatik to'lov orqali),
`tenant_manager` uni ~20 soniya ichida avtomatik topib, ikkala botini
ishga tushiradi — xizmatni qayta ishga tushirishning hojati yo'q.
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN, SQLITE_PATH
from services import database
from services.storage import SQLiteStorage
from services.tenant_middleware import IsAdminBot, IsCandidateBot, TenantMiddleware

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi. .env faylini .env.example asosida yarating va "
        "BotFather'dan olingan tokenni kiriting."
    )

logger = logging.getLogger("janob_hr_bot")

_TENANT_REFRESH_SECONDS = 20


def _build_dispatcher(fsm_storage: SQLiteStorage) -> Dispatcher:
    """Barcha mijozlar uchun UMUMIY dispatcher. Har bir kelgan yangilanish
    `TenantMiddleware` orqali qaysi mijozga (tenant_id) va qaysi rolga
    (bot_role: "candidate"/"admin") tegishli ekanini biladi."""
    from handlers import start, vacancy, questions, files, sell, contact, resume_upfront, create_bot
    from admin_bot import (
        handlers_menu, handlers_vacancy_list, handlers_vacancy_edit,
        handlers_decisions, handlers_interview, handlers_export,
    )

    dp = Dispatcher(storage=fsm_storage)
    dp.update.outer_middleware(TenantMiddleware())

    candidate_root = Router(name="candidate_root")
    candidate_root.message.filter(IsCandidateBot())
    candidate_root.callback_query.filter(IsCandidateBot())
    for r in (
        sell.router, start.router, create_bot.router, vacancy.router,
        resume_upfront.router, questions.router, files.router, contact.router,
    ):
        candidate_root.include_router(r)
    dp.include_router(candidate_root)

    admin_root = Router(name="admin_root")
    admin_root.message.filter(IsAdminBot())
    admin_root.callback_query.filter(IsAdminBot())
    for r in (
        handlers_menu.router, handlers_vacancy_list.router, handlers_vacancy_edit.router,
        handlers_decisions.router, handlers_interview.router, handlers_export.router,
    ):
        admin_root.include_router(r)
    dp.include_router(admin_root)

    return dp


async def _poll_bot(token: str, dp: Dispatcher, label: str):
    """Bitta botni CHEKSIZ tsiklda tinglaydi. Xato yuz bersa (masalan token
    bekor qilingan bo'lsa), jarayonni butunlay o'ldirmasdan, biroz kutib
    qayta urinadi."""
    while True:
        bot = None
        try:
            bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Polling boshlandi: %s", label)
            await dp.start_polling(bot, handle_signals=False)
        except Exception:
            logger.exception("Polling xatosi (%s) — 15 soniyadan keyin qayta urinamiz.", label)
            await asyncio.sleep(15)
        finally:
            if bot is not None:
                try:
                    await bot.session.close()
                except Exception:
                    pass


async def _tenant_manager(dp: Dispatcher):
    """Har ~20 soniyada FAOL mijozlar ro'yxatini tekshiradi va hali ishga
    tushirilmagan har biri uchun ikkita polling vazifasini (nomzod+admin
    bot) yaratadi. Xizmatni qayta ishga tushirmasdan, yangi faollashtirilgan
    mijozlar avtomatik qo'shiladi."""
    started_tenant_ids: set[int] = set()

    while True:
        try:
            tenants = await database.list_tenants(status="active")
            for tenant in tenants:
                if tenant["id"] in started_tenant_ids:
                    continue
                started_tenant_ids.add(tenant["id"])

                label = tenant["company_name"]
                asyncio.create_task(_poll_bot(tenant["bot_token"], dp, f"{label} — nomzod"))
                if tenant.get("admin_bot_token"):
                    asyncio.create_task(_poll_bot(tenant["admin_bot_token"], dp, f"{label} — admin"))
                logger.info(
                    "✅ Yangi faol mijoz uchun botlar ishga tushirildi: %s (id=%s)",
                    label, tenant["id"],
                )
        except Exception:
            logger.exception("Faol mijozlarni tekshirishda xato.")

        await asyncio.sleep(_TENANT_REFRESH_SECONDS)


async def main():
    await database.init_db()

    fsm_storage = SQLiteStorage(SQLITE_PATH)
    await fsm_storage.init()

    dp = _build_dispatcher(fsm_storage)

    tasks = [_tenant_manager(dp)]

    try:
        from userbot import is_userbot_configured, start_userbot

        if is_userbot_configured():
            tasks.append(start_userbot())
            logger.info("Userbot (to'lov tinglovchisi) ishga tushirilmoqda.")
        else:
            logger.info(
                "Userbot sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — "
                "to'lovni avtomatlashtirish o'chirilgan holda qoladi."
            )
    except Exception:
        logger.exception("Userbot modulini yuklab bo'lmadi — to'lov avtomatlashtirilmaydi.")

    logger.info("Janob HR (konsolidatsiyalangan) xizmati ishga tushdi ✅")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    asyncio.run(main())
