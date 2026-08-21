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

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, TokenBasedRequestHandler, setup_application
from aiohttp import web

from config import WEBHOOK_BASE_URL
from services import database
from services.storage import SQLiteStorage
from services.tenant_middleware import IsAdmin, IsNotAdmin, TenantMiddleware

logger = logging.getLogger("janob_hr_bot")

WEBHOOK_PATH = "/webhook/{bot_token}"


def _build_dispatcher() -> Dispatcher:
    """Barcha mijozlar uchun UMUMIY (bitta) Dispatcher — routerlar shu yerga ulanadi.
    Har bir yangilanish TenantMiddleware orqali o'z tenant_id/is_admin'ini oladi."""
    fsm_storage = SQLiteStorage(db_path=database.SQLITE_PATH)
    dp = Dispatcher(storage=fsm_storage)
    dp.update.outer_middleware(TenantMiddleware())

    # NOTE: haqiqiy handler routerlari (candidate + admin) keyingi bosqichda
    # shu yerga ulanadi — hozircha faqat infratuzilma (middleware + webhook
    # yo'naltirish) sinaladi. Masalan:
    #   from handlers import start, vacancy, questions, ...
    #   dp.include_router(start.router)  # is_admin filtersiz — hammaga ochiq
    #
    #   admin_root = Router()
    #   admin_root.message.filter(IsAdmin())
    #   admin_root.callback_query.filter(IsAdmin())
    #   admin_root.include_router(handlers_menu.router)
    #   ...
    #   dp.include_router(admin_root)

    return dp


async def register_new_tenant_webhook(app: web.Application, dp: Dispatcher, bot_token: str) -> str:
    """Yangi mijoz faollashtirilganda (Phase 4), serverni qayta ishga
    tushirmasdan uning webhook'ini o'rnatadi. Bot username'ini qaytaradi."""
    bot = Bot(token=bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    webhook_url = f"{WEBHOOK_BASE_URL}/webhook/{bot_token}"
    await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    me = await bot.get_me()
    logger.info("Yangi mijoz webhooki o'rnatildi: @%s", me.username)
    return me.username


async def on_startup(app: web.Application):
    dp: Dispatcher = app["dispatcher"]
    tenants = await database.list_tenants(status="active")
    for tenant in tenants:
        try:
            await register_new_tenant_webhook(app, dp, tenant["bot_token"])
        except Exception:
            logger.exception("Mijoz (id=%s) webhookini ornatib bolmadi.", tenant["id"])
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
