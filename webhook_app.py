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
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, TokenBasedRequestHandler, setup_application
from aiohttp import web

from config import WEBHOOK_BASE_URL
from services import database
from services.storage import SQLiteStorage
from services.tenant_middleware import IsAdminBot, IsCandidateBot, TenantMiddleware

logger = logging.getLogger("janob_hr_bot")

WEBHOOK_PATH = "/webhook/{bot_token}"


def _build_dispatcher() -> Dispatcher:
    """Barcha mijozlar uchun UMUMIY (bitta) Dispatcher — routerlar shu yerga ulanadi.
    Har bir yangilanish TenantMiddleware orqali o'z tenant_id/bot_role/is_admin'ini oladi.

    Nomzod routerlari — FAQAT nomzod-bot orqali kelgan yangilanishlarga ishlaydi
    (IsCandidateBot filtri). Admin routerlari — FAQAT Admin panel-bot orqali,
    VA shu mijozning admini bo'lgan foydalanuvchidan (IsAdminBot filtri).
    """
    from aiogram import Router

    from handlers import start, vacancy, questions, files, sell, contact, resume_upfront
    from admin_bot import (
        handlers_menu, handlers_vacancy_list, handlers_vacancy_edit,
        handlers_decisions, handlers_interview, handlers_export,
    )
    from services.tenant_middleware import IsAdminBot, IsCandidateBot

    fsm_storage = SQLiteStorage(db_path=database.SQLITE_PATH)
    dp = Dispatcher(storage=fsm_storage)
    dp.update.outer_middleware(TenantMiddleware())

    candidate_root = Router(name="candidate_root")
    candidate_root.message.filter(IsCandidateBot())
    candidate_root.callback_query.filter(IsCandidateBot())
    for r in (sell.router, start.router, vacancy.router, resume_upfront.router,
              questions.router, files.router, contact.router):
        candidate_root.include_router(r)
    dp.include_router(candidate_root)

    admin_root = Router(name="admin_root")
    admin_root.message.filter(IsAdminBot())
    admin_root.callback_query.filter(IsAdminBot())
    for r in (handlers_menu.router, handlers_vacancy_list.router, handlers_vacancy_edit.router,
              handlers_decisions.router, handlers_interview.router, handlers_export.router):
        admin_root.include_router(r)
    dp.include_router(admin_root)

    return dp


async def register_new_tenant_webhook(bot_token: str) -> str:
    """Yangi bot (nomzod yoki admin) uchun serverni qayta ishga tushirmasdan
    webhookni o'rnatadi. Bot username'ini qaytaradi."""
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{bot_token}"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    me = await bot.get_me()
    logger.info("Webhook o'rnatildi: @%s", me.username)
    return me.username


async def on_startup(app: web.Application):
    tenants = await database.list_tenants(status="active")
    for tenant in tenants:
        try:
            await register_new_tenant_webhook(tenant["bot_token"])
            if tenant.get("admin_bot_token"):
                await register_new_tenant_webhook(tenant["admin_bot_token"])
        except Exception:
            logger.exception("Mijoz (id=%s) webhooklarini ornatib bolmadi.", tenant["id"])
    logger.info("Webhook server ishga tushdi: %d ta faol mijoz.", len(tenants))


def create_app() -> web.Application:
    dp = _build_dispatcher()
    app = web.Application()
    app["dispatcher"] = dp

    handler = TokenBasedRequestHandler(dispatcher=dp)
    handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp)

    app.on_startup.append(on_startup)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=8080)
