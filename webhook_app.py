"""
Janob HR — ko'p mijozli webhook server (Phase 2).

Bitta veb-server barcha mijozlarning botlaridan kelayotgan yangilanishlarni
qabul qiladi. Har bir mijoz o'z URL manzilida (/webhook/{token}) xabar
qabul qiladi — aiogram avtomatik ravishda shu token bilan Bot obyektini
yaratadi/keshlaydi (TokenBasedRequestHandler).

Ishga tushirilganda, bazadagi barcha FAOL mijozlar uchun webhook o'rnatiladi.
Yangi mijoz keyinroq (Phase 3/4) `register_new_tenant_webhook()` orqali,
serverni qayta ishga tushirmasdan qo'shiladi.
"""

import asyncio
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import TokenBasedRequestHandler, setup_application
from aiohttp import web

from config import FOUNDER_BOT_TOKEN, MINI_APP_BASE_URL, WEBHOOK_BASE_URL
from services import database
from services.storage import SQLiteStorage
from services.tenant_middleware import TenantMiddleware

logger = logging.getLogger("janob_hr_bot")

WEBHOOK_PATH = "/webhook/{bot_token}"


def _build_dispatcher() -> Dispatcher:
    """Barcha mijozlar uchun UMUMIY (bitta) Dispatcher — routerlar shu yerga ulanadi.
    Har bir yangilanish TenantMiddleware orqali o'z tenant_id/bot_role/is_admin'ini oladi.

    Nomzod routerlari — FAQAT nomzod-bot orqali kelgan yangilanishlarga ishlaydi
    (IsCandidateBot filtri). Admin routerlari — FAQAT Admin panel-bot orqali,
    VA shu mijozning admini bo'lgan foydalanuvchidan (IsAdminBot filtri).
    """

    import founder_panel
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
    from services.tenant_middleware import IsAdminBot, IsCandidateBot, IsFounderBot

    fsm_storage = SQLiteStorage(db_path=database.SQLITE_PATH)
    dp = Dispatcher(storage=fsm_storage)
    dp.update.outer_middleware(TenantMiddleware())

    candidate_root = Router(name="candidate_root")
    candidate_root.message.filter(IsCandidateBot())
    candidate_root.callback_query.filter(IsCandidateBot())
    for r in (
        sell.router,
        create_bot.router,
        start.router,
        vacancy.router,
        resume_upfront.router,
        questions.router,
        files.router,
        contact.router,
    ):
        candidate_root.include_router(r)
    dp.include_router(candidate_root)

    admin_root = Router(name="admin_root")
    admin_root.message.filter(IsAdminBot())
    admin_root.callback_query.filter(IsAdminBot())
    for r in (
        handlers_menu.router,
        handlers_billing.router,
        handlers_candidates.router,
        handlers_vacancy_list.router,
        handlers_vacancy_edit.router,
        handlers_decisions.router,
        handlers_interview.router,
        handlers_export.router,
    ):
        admin_root.include_router(r)
    dp.include_router(admin_root)

    # Founder Bot — asosiy webhook server bilan BIR XIL dispatcher/bazani
    # ishlatadi (alohida Render xizmati sifatida emas). Shu tufayli u
    # webhook_app.py bilan bir xil (jonli) data.db faylini ko'radi —
    # ikkita ajratilgan fayl tizimi orasida ma'lumot uzilib qolmaydi.
    founder_root = Router(name="founder_root")
    founder_root.message.filter(IsFounderBot())
    founder_root.callback_query.filter(IsFounderBot())
    founder_root.include_router(founder_panel.router)
    dp.include_router(founder_root)

    return dp


async def register_new_tenant_webhook(bot_token: str) -> str:
    """Yangi bot (nomzod yoki admin) uchun serverni qayta ishga tushirmasdan
    webhookni o'rnatadi. Bot username'ini qaytaradi."""
    if not WEBHOOK_BASE_URL:
        raise RuntimeError("WEBHOOK_BASE_URL sozlanmagan.")

    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{bot_token}"
        await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
        me = await bot.get_me()
        logger.info("Webhook o'rnatildi: @%s", me.username)
        return me.username
    finally:
        # Bu vaqtinchalik Bot obyekti faqat webhook o'rnatish uchun
        # yaratiladi — ishlatib bo'lgach sessiyasi albatta yopilishi kerak,
        # aks holda "Unclosed client session" xatosi va resurs sizib
        # chiqishi (memory/file descriptor leak) yuzaga keladi.
        await bot.session.close()


async def configure_admin_miniapp(tenant: dict) -> None:
    """Tenant admin botiga Mini App menyu tugmasini o'rnatadi."""
    if not tenant.get("admin_bot_token") or not WEBHOOK_BASE_URL:
        return
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")
    admin_bot = Bot(token=tenant["admin_bot_token"])
    try:
        await admin_bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Boshqaruv paneli",
                web_app=WebAppInfo(url=f"{miniapp_base}/{tenant['id']}"),
            )
        )
    finally:
        await admin_bot.session.close()


async def on_startup(app: web.Application):
    await database.init_db()
    # Dispatcher ishlatadigan persistent FSM jadvali database.init_db() tarkibiga
    # kirmaydi. Uni alohida yaratmasak, yangi serverda birinchi /start so'rovi
    # "no such table: fsm_storage" bilan yiqiladi.
    await app["dispatcher"].storage.init()
    from services.reminders import run_reminders_forever

    asyncio.create_task(run_reminders_forever())
    tenants = await database.list_tenants(status="active")
    for tenant in tenants:
        try:
            await register_new_tenant_webhook(tenant["bot_token"])
            if tenant.get("admin_bot_token"):
                await register_new_tenant_webhook(tenant["admin_bot_token"])
                await configure_admin_miniapp(tenant)
        except Exception:
            logger.exception(
                "Mijoz (id=%s) webhooklarini ornatib bolmadi.", tenant["id"]
            )

    if FOUNDER_BOT_TOKEN:
        try:
            await register_new_tenant_webhook(FOUNDER_BOT_TOKEN)
            logger.info("Founder Bot webhooki ornatildi.")
        except Exception:
            logger.exception("Founder Bot webhookini ornatib bolmadi.")

    # To'lovlarni avtomatik aniqlovchi userbot — ALOHIDA Render xizmati
    # sifatida EMAS, balki shu jarayon ichida fon vazifasi (background task)
    # sifatida ishga tushiriladi. Sabab: u ham xuddi shu (jonli) data.db
    # faylini ko'rishi SHART — aks holda yangi mijozlarning to'lov
    # buyurtmalarini hech qachon topa olmaydi.
    # try/except bilan o'ralgan: bu — QO'SHIMCHA (ixtiyoriy) xususiyat,
    # undagi har qanday kutilmagan xato ASOSIY bot serverini yiqitmasligi
    # SHART (nomzodlar va adminlar uchun bot ishlashda davom etishi kerak).
    try:
        from userbot import is_userbot_configured, start_userbot

        if is_userbot_configured():
            asyncio.create_task(start_userbot())
            logger.info(
                "Userbot (to'lovlarni aniqlash) fon vazifasi sifatida ishga tushirildi."
            )
        else:
            logger.info(
                "Userbot sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — o'tkazib yuborildi."
            )
    except Exception:
        logger.exception("Userbot ishga tushmadi — asosiy bot ishlashda davom etadi.")

    logger.info("Webhook server ishga tushdi: %d ta faol mijoz.", len(tenants))


def create_app() -> web.Application:
    dp = _build_dispatcher()
    app = web.Application()
    app["dispatcher"] = dp

    # TokenBasedRequestHandler har bir tenant tokeni uchun Bot obyektini o'zi
    # yaratadi. Default parse mode berilmasa, <b> kabi HTML teglar foydalanuvchiga
    # oddiy matn bo'lib ko'rinadi.
    handler = TokenBasedRequestHandler(
        dispatcher=dp,
        bot_settings={
            "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
        },
    )
    handler.register(app, path=WEBHOOK_PATH)
    from miniapp_api import register_miniapp

    register_miniapp(app)
    setup_application(app, dp)

    app.on_startup.append(on_startup)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
