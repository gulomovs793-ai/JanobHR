"""
Janob HR — ko'p mijozli webhook server (Phase 2).

Bitta veb-server barcha mijozlarning botlaridan kelayotgan yangilanishlarni
qabul qiladi. Telegram bot tokenlari URLga qo'yilmaydi: har bir bot uchun
HMAC orqali alohida opaque webhook ID va Telegram secret-token hosil qilinadi.
Reverse-proxy/access loglarda haqiqiy BotFather tokeni ko'rinmaydi.

Ishga tushirilganda, bazadagi barcha FAOL mijozlar uchun webhook o'rnatiladi.
Yangi mijoz keyinroq (Phase 3/4) `register_new_tenant_webhook()` orqali,
serverni qayta ishga tushirmasdan qo'shiladi.
"""

import asyncio
import hashlib
import hmac
import logging
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import BaseRequestHandler, setup_application
from aiohttp import web

from config import (
    BOT_TOKEN,
    FOUNDER_BOT_TOKEN,
    FOUNDER_USER_IDS,
    MINI_APP_BASE_URL,
    PARTNER_BOT_TOKEN,
    PAYMENT_LISTENER_ENABLED,
    PAYMENT_ROUTER_SECRET,
    TELEGRAM_USERBOT_SESSION,
    WEBHOOK_BASE_URL,
    WEBHOOK_ROUTING_SECRET,
)
from services import database
from services.storage import SQLiteStorage
from services.tenant_middleware import TenantMiddleware

logger = logging.getLogger("janob_hr_bot")

WEBHOOK_PATH = "/telegram/{webhook_id}"
_SECURE_WEBHOOK_HANDLER: "SecureMultiBotRequestHandler | None" = None


def _webhook_master_secret() -> str:
    """Stable server-side secret used only to derive webhook route IDs/secrets.

    A dedicated WEBHOOK_ROUTING_SECRET is preferred. Existing high-entropy
    production secrets are safe fallbacks so a deploy cannot accidentally
    revert to token-in-URL routing just because the new env var is missing.
    """
    secret = WEBHOOK_ROUTING_SECRET or PAYMENT_ROUTER_SECRET or TELEGRAM_USERBOT_SESSION
    if not secret:
        raise RuntimeError(
            "Webhook xavfsizlik secreti sozlanmagan: WEBHOOK_ROUTING_SECRET kiriting."
        )
    return secret


def _derive_webhook_identity(bot_token: str) -> tuple[str, str]:
    master = _webhook_master_secret().encode()
    route_id = hmac.new(
        master, f"route:{bot_token}".encode(), hashlib.sha256
    ).hexdigest()[:40]
    telegram_secret = hmac.new(
        master, f"secret:{bot_token}".encode(), hashlib.sha256
    ).hexdigest()
    return route_id, telegram_secret


class SecureMultiBotRequestHandler(BaseRequestHandler):
    """Multi-bot webhook handler that never puts BotFather tokens in URLs."""

    def __init__(self, dispatcher: Dispatcher, *, handle_in_background: bool = True):
        super().__init__(dispatcher=dispatcher, handle_in_background=handle_in_background)
        self.bots: dict[str, Bot] = {}

    def add_bot(self, bot_token: str) -> Bot:
        route_id, _ = _derive_webhook_identity(bot_token)
        bot = self.bots.get(route_id)
        if bot is None:
            bot = Bot(
                token=bot_token,
                default=DefaultBotProperties(parse_mode=ParseMode.HTML),
            )
            self.bots[route_id] = bot
        return bot

    async def resolve_bot(self, request: web.Request) -> Bot:
        bot = self.bots.get(request.match_info["webhook_id"])
        if bot is None:
            raise web.HTTPNotFound()
        return bot

    def verify_secret(self, telegram_secret_token: str, bot: Bot) -> bool:
        if not telegram_secret_token:
            return False
        _, expected = _derive_webhook_identity(bot.token)
        return hmac.compare_digest(telegram_secret_token, expected)

    async def close(self) -> None:
        tasks = list(self._background_feed_update_tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for bot in self.bots.values():
            await bot.session.close()


def _spawn_background_task(app: web.Application, coroutine) -> asyncio.Task:
    task = asyncio.create_task(coroutine)
    app["background_tasks"].add(task)
    task.add_done_callback(app["background_tasks"].discard)
    return task


async def on_shutdown(app: web.Application) -> None:
    tasks = list(app.get("background_tasks", set()))
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if _SECURE_WEBHOOK_HANDLER is not None:
        await _SECURE_WEBHOOK_HANDLER.close()


def _build_dispatcher() -> Dispatcher:
    """Barcha mijozlar uchun UMUMIY (bitta) Dispatcher — routerlar shu yerga ulanadi.
    Har bir yangilanish TenantMiddleware orqali o'z tenant_id/bot_role/is_admin'ini oladi.

    Nomzod routerlari — FAQAT nomzod-bot orqali kelgan yangilanishlarga ishlaydi
    (IsCandidateBot filtri). Admin routerlari — FAQAT Admin panel-bot orqali,
    VA shu mijozning admini bo'lgan foydalanuvchidan (IsAdminBot filtri).
    """

    import founder_panel
    import partner_bot
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
        demo,
        files,
        questions,
        resume_upfront,
        sell,
        start,
        vacancy,
    )
    from partner_payout_bot import founder_payout_router, payout_router
    from services.tenant_middleware import (
        IsAdminBot,
        IsCandidateBot,
        IsFounderBot,
        IsPartnerBot,
    )

    fsm_storage = SQLiteStorage(db_path=database.SQLITE_PATH)
    dp = Dispatcher(storage=fsm_storage)
    dp.update.outer_middleware(TenantMiddleware())

    candidate_root = Router(name="candidate_root")
    candidate_root.message.filter(IsCandidateBot())
    candidate_root.callback_query.filter(IsCandidateBot())
    for r in (
        sell.router,
        create_bot.router,
        demo.router,
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

    founder_root = Router(name="founder_root")
    founder_root.message.filter(IsFounderBot())
    founder_root.callback_query.filter(IsFounderBot())
    founder_root.include_router(founder_panel.router)
    founder_root.include_router(founder_payout_router)
    dp.include_router(founder_root)

    partner_root = Router(name="partner_root")
    partner_root.message.filter(IsPartnerBot())
    partner_root.callback_query.filter(IsPartnerBot())
    partner_root.include_router(partner_bot.router)
    partner_root.include_router(payout_router)
    dp.include_router(partner_root)

    return dp


async def register_new_tenant_webhook(bot_token: str) -> str:
    """Install a non-secret URL plus Telegram secret-token for one bot."""
    if not WEBHOOK_BASE_URL:
        raise RuntimeError("WEBHOOK_BASE_URL sozlanmagan.")
    if _SECURE_WEBHOOK_HANDLER is None:
        raise RuntimeError("Secure webhook handler hali ishga tushmagan.")

    route_id, telegram_secret = _derive_webhook_identity(bot_token)
    bot = _SECURE_WEBHOOK_HANDLER.add_bot(bot_token)
    webhook_url = f"{WEBHOOK_BASE_URL.rstrip('/')}/telegram/{route_id}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=telegram_secret,
        drop_pending_updates=False,
    )
    me = await bot.get_me()
    logger.info("Xavfsiz webhook o'rnatildi: @%s", me.username)
    return me.username


async def configure_admin_miniapp(tenant: dict) -> None:
    """Tenant admin botiga Mini App menyu tugmasini o'rnatadi."""
    if not tenant.get("admin_bot_token") or not WEBHOOK_BASE_URL:
        return
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")
    admin_bot = Bot(token=tenant["admin_bot_token"])
    try:
        menu_button = MenuButtonWebApp(
            text="Boshqaruv paneli",
            web_app=WebAppInfo(url=f"{miniapp_base}/{tenant['id']}"),
        )
        await admin_bot.set_chat_menu_button(menu_button=menu_button)
        for admin_id in tenant.get("admin_user_ids", []):
            try:
                await admin_bot.set_chat_menu_button(
                    chat_id=admin_id, menu_button=menu_button
                )
            except Exception:
                logger.exception(
                    "Admin Mini App menu tugmasi chatga ulanmagan: tenant_id=%s admin_id=%s",
                    tenant.get("id"), admin_id,
                )
    finally:
        await admin_bot.session.close()


async def configure_founder_miniapp() -> None:
    """Founder bot menyusiga xavfsiz boshqaruv Mini Appini ulaydi."""
    if not FOUNDER_BOT_TOKEN or not WEBHOOK_BASE_URL:
        return
    from aiogram.types import MenuButtonWebApp, WebAppInfo

    founder_bot = Bot(token=FOUNDER_BOT_TOKEN)
    try:
        await founder_bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Founder panel",
                web_app=WebAppInfo(url=f"{WEBHOOK_BASE_URL.rstrip('/')}/founder"),
            )
        )
    finally:
        await founder_bot.session.close()


async def on_startup(app: web.Application):
    await database.init_db()
    await app["dispatcher"].storage.init()
    try:
        from services import partner_database as pdb

        reconciliation = await pdb.reconcile_approved_partner_sales()
        if reconciliation["found"]:
            logger.info("Partner commission reconcile: %s", reconciliation)
    except Exception:
        logger.exception("Partner commission startup reconcile ishlamadi.")
    import partner_bot
    from services.backup import run_backups_forever
    from services.payment_automation import (
        reconcile_approved_orders,
        run_approved_order_recovery_forever,
    )
    from services.reminders import run_reminders_forever
    from services.tenant_activation import activate_tenant
    from userbot import _notify_founders

    _spawn_background_task(app, run_reminders_forever())
    _spawn_background_task(app, run_backups_forever())

    try:
        recovery = await reconcile_approved_orders(
            activate_tenant,
            notify_founders=_notify_founders,
        )
        if recovery["found"]:
            logger.info("Approved payment startup recovery: %s", recovery)
    except Exception:
        logger.exception("Approved payment startup recovery ishlamadi.")
    _spawn_background_task(
        app,
        run_approved_order_recovery_forever(
            activate_tenant,
            notify_founders=_notify_founders,
        ),
    )
    if FOUNDER_BOT_TOKEN and FOUNDER_USER_IDS:
        from partner_payout_bot import run_payout_reminders

        _spawn_background_task(app, run_payout_reminders())

    pending_trials = await database.list_tenants(status="pending")
    for pending in pending_trials:
        if pending.get("plan_code") != "trial":
            continue
        result = await activate_tenant(pending["id"])
        if result.get("ok"):
            logger.info(
                "Pending trial avtomatik faollashtirildi: tenant_id=%s",
                pending["id"],
            )
        else:
            logger.warning(
                "Pending trialni avtomatik faollashtirib bo'lmadi: tenant_id=%s error=%s",
                pending["id"],
                result.get("error"),
            )

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

    # Public Janob HR bot is not necessarily stored as a customer tenant.
    # Register it explicitly so referral deep-links reach the business flow.
    if BOT_TOKEN and not await database.get_tenant_by_role_token(BOT_TOKEN):
        try:
            await register_new_tenant_webhook(BOT_TOKEN)
            logger.info("Asosiy Janob HR bot webhooki o'rnatildi.")
        except Exception:
            logger.exception("Asosiy Janob HR bot webhookini o'rnatib bo'lmadi.")

    if FOUNDER_BOT_TOKEN:
        try:
            await register_new_tenant_webhook(FOUNDER_BOT_TOKEN)
            await configure_founder_miniapp()
            logger.info("Founder Bot webhooki ornatildi.")
        except Exception:
            logger.exception("Founder Bot webhookini ornatib bolmadi.")

    if PARTNER_BOT_TOKEN and PARTNER_BOT_TOKEN != BOT_TOKEN:
        try:
            await register_new_tenant_webhook(PARTNER_BOT_TOKEN)
            partner_bot_instance = _SECURE_WEBHOOK_HANDLER.add_bot(PARTNER_BOT_TOKEN)
            await partner_bot.configure_partner_miniapp_menu(partner_bot_instance)
            logger.info("Partner Bot webhooki va ko'k Mini App menyusi o'rnatildi.")
        except Exception:
            logger.exception("Partner Bot webhooki yoki Mini App menyusi o'rnatilmadi.")

    # Partner Bot shared webhook orqali ishlaydi. U alohida polling task sifatida
    # qayta ishga tushirilmaydi — aks holda bitta update ikki marta ishlanadi.
    logger.info("Partner Bot shared webhook orqali ishlayapti; polling yo'q.")

    try:
        from userbot import is_userbot_configured, start_userbot

        if not PAYMENT_LISTENER_ENABLED:
            logger.info(
                "Janob HR Telegram payment listener o'chirilgan — signed router ishlatiladi."
            )
        elif is_userbot_configured():
            _spawn_background_task(app, start_userbot())
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


async def internal_payment_notification(request: web.Request) -> web.Response:
    """Signed notification from the single shared-card Telegram listener."""
    supplied = request.headers.get("X-Payment-Router-Secret", "")
    if not PAYMENT_ROUTER_SECRET:
        logger.error("PAYMENT_ROUTER_SECRET sozlanmagan; routed payment rad etildi.")
        raise web.HTTPServiceUnavailable(text="payment router not configured")
    if not supplied or not hmac.compare_digest(supplied, PAYMENT_ROUTER_SECRET):
        logger.warning("Noto'g'ri payment router secret bilan so'rov rad etildi.")
        raise web.HTTPUnauthorized(text="unauthorized")

    try:
        payload = await request.json()
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="invalid json") from exc
    if not isinstance(payload, dict):
        raise web.HTTPBadRequest(text="invalid notification")
    raw_text = str(payload.get("raw_text") or "").strip()
    if not raw_text or len(raw_text) > 5000:
        raise web.HTTPBadRequest(text="invalid notification")

    from services.payment_automation import handle_payment_notification
    from userbot import (
        _activate_tenant_wrapper,
        _notify_founders,
        _notify_tenant_payment_approved,
    )

    result = await handle_payment_notification(
        raw_text,
        _notify_founders,
        _activate_tenant_wrapper,
        notify_no_match=False,
    )
    if result.get("status") == "approved":
        await _notify_tenant_payment_approved(result)
    logger.info("[payment-router] Natija: %s", result.get("status"))
    return web.json_response(result)


async def health(request: web.Request) -> web.Response:
    db_ok = await database.healthcheck()
    ok = bool(WEBHOOK_BASE_URL) and db_ok
    return web.json_response(
        {"ok": ok, "database": db_ok, "webhook_base_url": bool(WEBHOOK_BASE_URL)},
        status=200 if ok else 503,
    )


def create_app() -> web.Application:
    global _SECURE_WEBHOOK_HANDLER

    dp = _build_dispatcher()
    app = web.Application()
    app["dispatcher"] = dp
    app["background_tasks"] = set()
    app.on_shutdown.append(on_shutdown)

    handler = SecureMultiBotRequestHandler(
        dispatcher=dp,
        handle_in_background=True,
    )
    _SECURE_WEBHOOK_HANDLER = handler
    handler.register(app, path=WEBHOOK_PATH)
    from founder_miniapp_api import register_founder_miniapp
    from miniapp_api import register_miniapp
    from partner_miniapp_api import register_partner_miniapp

    register_miniapp(app)
    register_founder_miniapp(app)
    register_partner_miniapp(app)
    app.router.add_get("/health", health)
    app.router.add_post("/internal/payment-notification", internal_payment_notification)
    setup_application(app, dp)

    app.on_startup.append(on_startup)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    web.run_app(create_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
