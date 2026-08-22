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


async def _run_all_tenants(fsm_storage: SQLiteStorage):
    """Bitta Dispatcher (BIR MARTA quriladi — routerlarni ikkinchi marta
    ulash mumkin emas!) barcha faol mijozlarning BARCHA botlarini BITTA
    `start_polling()` chaqiruvida birga poll qiladi.

    Yangi mijoz faollashtirilganda (yoki mavjudi o'chirilganda), joriy
    pollingni to'xtatib, YANGILANGAN bot ro'yxati bilan qayta boshlaydi —
    bu bir necha soniyalik qisqa uzilishga olib keladi, lekin ishonchli va
    aiogram'ning "bitta Dispatcher — bir vaqtda bitta start_polling"
    cheklovi bilan mos ishlaydi (aks holda ba'zi botlar abadiy "osilib
    qolishi" mumkin — bu haqiqiy, sinovdan o'tgan xato edi)."""
    dp = _build_dispatcher(fsm_storage)
    known_tenant_ids: set[int] = set()
    polling_task: asyncio.Task | None = None

    while True:
        try:
            tenants = await database.list_tenants(statuses=["active", "trial", "trial_expired"])
            active_ids = {t["id"] for t in tenants}

            if active_ids != known_tenant_ids:
                if polling_task is not None and not polling_task.done():
                    logger.info("Mijozlar tarkibi o'zgardi — pollingni qayta ishga tushiramiz.")
                    await dp.stop_polling()
                    polling_task.cancel()
                    try:
                        await polling_task
                    except (asyncio.CancelledError, Exception):
                        pass

                bots = []
                for tenant in tenants:
                    cand_bot = Bot(token=tenant["bot_token"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                    await cand_bot.delete_webhook(drop_pending_updates=True)
                    bots.append(cand_bot)

                    if tenant.get("admin_bot_token"):
                        admin_bot = Bot(token=tenant["admin_bot_token"], default=DefaultBotProperties(parse_mode=ParseMode.HTML))
                        await admin_bot.delete_webhook(drop_pending_updates=True)
                        bots.append(admin_bot)

                if bots:
                    logger.info(
                        "✅ Polling (qayta) boshlandi: %d ta mijoz, %d ta bot — %s",
                        len(tenants), len(bots), ", ".join(t["company_name"] for t in tenants),
                    )
                    polling_task = asyncio.create_task(dp.start_polling(*bots, handle_signals=False))
                else:
                    polling_task = None

                known_tenant_ids = active_ids
        except Exception:
            logger.exception("Faol mijozlarni tekshirishda/pollingni yangilashda xato.")

        await asyncio.sleep(_TENANT_REFRESH_SECONDS)


async def main():
    await database.init_db()

    fsm_storage = SQLiteStorage(SQLITE_PATH)
    await fsm_storage.init()

    tasks = [_run_all_tenants(fsm_storage)]

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
