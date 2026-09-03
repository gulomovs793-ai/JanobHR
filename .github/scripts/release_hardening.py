from pathlib import Path


def read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_config() -> None:
    path = "config.py"
    text = read(path)
    old = """WEBHOOK_BASE_URL = os.getenv(\"WEBHOOK_BASE_URL\", \"\").strip() or (\n    f\"https://{_render_hostname}\" if _render_hostname else \"\"\n)\n\n# Admin bot ichidan ochiladigan Telegram Mini App. Bo'sh qoldirilsa\n"""
    new = """WEBHOOK_BASE_URL = os.getenv(\"WEBHOOK_BASE_URL\", \"\").strip() or (\n    f\"https://{_render_hostname}\" if _render_hostname else \"\"\n)\n\n# Webhook URL ichida Telegram bot tokeni HECH QACHON ishlatilmaydi.\n# Alohida master-secret berish tavsiya etiladi. Productionda u bo'sh bo'lsa,\n# webhook_app mavjud yuqori-entropiyali server secretlaridan xavfsiz fallback qiladi.\nWEBHOOK_ROUTING_SECRET = os.getenv(\"WEBHOOK_ROUTING_SECRET\", \"\").strip()\n\n# Admin bot ichidan ochiladigan Telegram Mini App. Bo'sh qoldirilsa\n"""
    text = replace_once(text, old, new, label="config webhook secret")
    write(path, text)


def patch_webhook_app() -> None:
    path = "webhook_app.py"
    text = read(path)

    old_doc = """Bitta veb-server barcha mijozlarning botlaridan kelayotgan yangilanishlarni\nqabul qiladi. Har bir mijoz o'z URL manzilida (/webhook/{token}) xabar\nqabul qiladi — aiogram avtomatik ravishda shu token bilan Bot obyektini\nyaratadi/keshlaydi (TokenBasedRequestHandler).\n"""
    new_doc = """Bitta veb-server barcha mijozlarning botlaridan kelayotgan yangilanishlarni\nqabul qiladi. Telegram bot tokenlari URLga qo'yilmaydi: har bir bot uchun\nHMAC orqali alohida opaque webhook ID va Telegram secret-token hosil qilinadi.\nReverse-proxy/access loglarda haqiqiy BotFather tokeni ko'rinmaydi.\n"""
    text = replace_once(text, old_doc, new_doc, label="webhook doc")

    text = replace_once(
        text,
        "import asyncio\nimport hmac\nimport logging\nimport os\n",
        "import asyncio\nimport hashlib\nimport hmac\nimport logging\nimport os\n",
        label="webhook imports",
    )
    text = replace_once(
        text,
        "from aiogram.webhook.aiohttp_server import TokenBasedRequestHandler, setup_application\n",
        "from aiogram.webhook.aiohttp_server import BaseRequestHandler, setup_application\n",
        label="webhook handler import",
    )
    old_cfg = """    PAYMENT_LISTENER_ENABLED,\n    PAYMENT_ROUTER_SECRET,\n    WEBHOOK_BASE_URL,\n)\n"""
    new_cfg = """    PAYMENT_LISTENER_ENABLED,\n    PAYMENT_ROUTER_SECRET,\n    TELEGRAM_USERBOT_SESSION,\n    WEBHOOK_BASE_URL,\n    WEBHOOK_ROUTING_SECRET,\n)\n"""
    text = replace_once(text, old_cfg, new_cfg, label="webhook config imports")

    old_header = """logger = logging.getLogger(\"janob_hr_bot\")\n\nWEBHOOK_PATH = \"/webhook/{bot_token}\"\n\n\ndef _build_dispatcher() -> Dispatcher:\n"""
    new_header = '''logger = logging.getLogger("janob_hr_bot")

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


def _build_dispatcher() -> Dispatcher:
'''
    text = replace_once(text, old_header, new_header, label="secure webhook header")

    start = text.index("async def register_new_tenant_webhook(bot_token: str) -> str:")
    end = text.index("\n\nasync def configure_admin_miniapp", start)
    new_register = '''async def register_new_tenant_webhook(bot_token: str) -> str:
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
'''
    text = text[:start] + new_register + text[end:]

    text = replace_once(
        text,
        """    from services.reminders import run_reminders_forever\n    from services.tenant_activation import activate_tenant\n\n    asyncio.create_task(run_reminders_forever())\n""",
        """    from services.backup import run_backups_forever\n    from services.reminders import run_reminders_forever\n    from services.tenant_activation import activate_tenant\n\n    _spawn_background_task(app, run_reminders_forever())\n    _spawn_background_task(app, run_backups_forever())\n""",
        label="background startup",
    )
    text = replace_once(
        text,
        """        elif is_userbot_configured():\n            asyncio.create_task(start_userbot())\n            logger.info(\n""",
        """        elif is_userbot_configured():\n            _spawn_background_task(app, start_userbot())\n            logger.info(\n""",
        label="userbot task tracking",
    )

    old_create = '''def create_app() -> web.Application:
    dp = _build_dispatcher()
    app = web.Application()
    app["dispatcher"] = dp

    # TokenBasedRequestHandler har bir tenant tokeni uchun Bot obyektini o'zi
    # yaratadi. Default parse mode berilmasa, <b> kabi HTML teglar foydalanuvchiga
    # oddiy matn bo'lib ko'rinadi.
    handler = TokenBasedRequestHandler(
        dispatcher=dp,
        # AI tahlili bir necha soniya olsa ham Telegram webhook HTTP javobini
        # kutib turmaydi. Aks holda Telegram bir xil update'ni retry qilib,
        # nomzodga bir savol ikki marta yuborilishi mumkin.
        handle_in_background=True,
        bot_settings={
            "default": DefaultBotProperties(parse_mode=ParseMode.HTML),
        },
    )
    handler.register(app, path=WEBHOOK_PATH)
'''
    new_create = '''def create_app() -> web.Application:
    global _SECURE_WEBHOOK_HANDLER

    dp = _build_dispatcher()
    app = web.Application()
    app["dispatcher"] = dp
    app["background_tasks"] = set()
    app.on_shutdown.append(on_shutdown)

    # Opaque route ID + Telegram secret-token. BotFather tokeni URL/access-logga
    # hech qachon tushmaydi.
    handler = SecureMultiBotRequestHandler(
        dispatcher=dp,
        handle_in_background=True,
    )
    _SECURE_WEBHOOK_HANDLER = handler
    handler.register(app, path=WEBHOOK_PATH)
'''
    text = replace_once(text, old_create, new_create, label="create app secure handler")

    if "/webhook/{bot_token}" in text or "TokenBasedRequestHandler" in text:
        raise RuntimeError("Unsafe token-in-URL webhook reference still present")
    write(path, text)


def patch_tenant_activation() -> None:
    path = "services/tenant_activation.py"
    text = read(path)
    start = text.index("async def activate_tenant(tenant_id: int) -> dict:")
    new_func = '''async def activate_tenant(tenant_id: int) -> dict:
    """Provision BOTH bots completely, then mark a new tenant active.

    Critical invariant: a pending tenant is never committed as ``active`` until
    candidate webhook, admin webhook and Admin Mini App configuration all
    succeeded. Existing active tenants are reconciled idempotently on retry.
    """
    from webhook_app import configure_admin_miniapp, register_new_tenant_webhook

    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Mijoz topilmadi."}
    if not tenant.get("bot_token") or not tenant.get("admin_bot_token"):
        return {"ok": False, "error": "Nomzod yoki admin bot tokeni yetishmayapti."}

    try:
        cand_username = await register_new_tenant_webhook(tenant["bot_token"])
        admin_username = await register_new_tenant_webhook(tenant["admin_bot_token"])
        prepared = dict(tenant)
        prepared["id"] = tenant_id
        prepared["bot_username"] = cand_username
        prepared["admin_bot_username"] = admin_username
        await configure_admin_miniapp(prepared)
    except Exception:
        logger.exception("Mijoz (id=%s) provisioningini yakunlab bo'lmadi.", tenant_id)
        return {
            "ok": False,
            "error": "Botlarni to'liq sozlashda xato — token/webhook/Mini Appni tekshiring.",
        }

    # DB commit is deliberately last. If anything above fails, a NEW tenant
    # remains pending and the next retry can safely reconcile everything.
    await database.set_admin_bot_username(tenant_id, admin_username)
    if tenant.get("status") != "active" or tenant.get("bot_username") != cand_username:
        await database.update_tenant_status(
            tenant_id, "active", bot_username=cand_username
        )

    if tenant["admin_user_ids"]:
        notify_bot = Bot(token=tenant["admin_bot_token"])
        try:
            await notify_bot.send_message(
                chat_id=tenant["admin_user_ids"][0],
                text=(
                    "🎉 Botlaringiz faollashtirildi! Endi to'liq ishlatishingiz mumkin.\\n\\n"
                    f"Admin panel: @{admin_username}\\nNomzod-bot: @{cand_username}"
                ),
            )
        except Exception:
            logger.exception(
                "Mijozga faollashtirish xabarini yuborib bo'lmadi (tenant_id=%s).",
                tenant_id,
            )
        finally:
            await notify_bot.session.close()

    return {
        "ok": True,
        "candidate_username": cand_username,
        "admin_username": admin_username,
    }
'''
    text = text[:start] + new_func
    write(path, text)


def patch_payment_automation() -> None:
    path = "services/payment_automation.py"
    text = read(path)
    text = replace_once(
        text,
        "import hashlib\nimport logging\nimport random\nimport re\n",
        "import asyncio\nimport hashlib\nimport logging\nimport random\nimport re\n",
        label="payment asyncio import",
    )
    text = replace_once(
        text,
        "from datetime import datetime, timedelta, timezone\n\nfrom config import",
        "from datetime import datetime, timedelta, timezone\n\nimport aiosqlite\n\nfrom config import",
        label="payment sqlite import",
    )

    start = text.index("async def _pick_unique_amount")
    end = text.index("async def handle_payment_notification", start)
    new_block = '''_PAYMENT_OFFSET_MAX = 1999
_AMOUNT_RESERVATION_HOURS = 24


async def _expire_stale_payment_orders(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    async with aiosqlite.connect(database.SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute(
            "UPDATE payment_orders SET status='expired', "
            "decided_at=COALESCE(decided_at, ?) "
            "WHERE status='awaiting_payment' AND expires_at<=?",
            (now_iso, now_iso),
        )
        await db.commit()


async def _recent_non_live_orders(amount: int) -> list[dict]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=_AMOUNT_RESERVATION_HOURS)
    ).isoformat()
    async with aiosqlite.connect(database.SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE amount=? AND created_at>=? "
            "AND status IN ('expired','cancelled','approved','needs_review') "
            "ORDER BY id DESC",
            (amount, cutoff),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def _handle_late_or_duplicate_payment(amount: int, notify_founders) -> dict | None:
    recent = await _recent_non_live_orders(amount)
    if not recent:
        return None

    # Amounts are reserved for 24h, so a recent approved order cannot belong to
    # a new customer. Treat a repeated bank notification as duplicate, not money
    # for a different tenant.
    if recent[0]["status"] == "approved":
        return {"status": "duplicate", "amount": amount}

    unresolved = [
        order for order in recent if order["status"] in {"expired", "cancelled", "needs_review"}
    ]
    if len(unresolved) == 1:
        order = unresolved[0]
        await database.mark_payment_order_needs_review(
            order["id"], "To'lov order muddati/bekor qilingandan keyin keldi"
        )
        await notify_founders(
            f"⚠️ Kechikkan to'lov: {amount:,} so'm. "
            f"Buyurtma {order['order_code']} endi avtomatik yoqilmadi; qo'lda tekshiring."
        )
        return {"status": "needs_review", "amount": amount}

    if unresolved:
        await notify_founders(
            f"⚠️ Kechikkan/noaniq to'lov: {amount:,} so'm bir nechta eski "
            "buyurtmaga mos keldi. Qo'lda tekshiring."
        )
        return {"status": "ambiguous", "amount": amount}
    return None


async def create_payment_order(
    tenant_id: int,
    base_amount: int | None = None,
    *,
    plan_code: str = "start",
    billing_months: int = 1,
) -> dict:
    """Create an order atomically and reserve its exact amount for 24 hours.

    ``BEGIN IMMEDIATE`` serializes competing writers, eliminating the old
    check-then-insert race. Expired/cancelled/approved recent amounts stay
    reserved so a delayed bank notification can never activate a different
    customer's newly-created order.
    """
    base_amount = base_amount or MONTHLY_PRICE_SOM

    for attempt in range(4):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(minutes=ORDER_TTL_MINUTES)).isoformat()
        reservation_cutoff = (
            now - timedelta(hours=_AMOUNT_RESERVATION_HOURS)
        ).isoformat()

        try:
            async with aiosqlite.connect(database.SQLITE_PATH, timeout=10) as db:
                await db.execute("PRAGMA busy_timeout=10000")
                await db.execute("BEGIN IMMEDIATE")

                await db.execute(
                    "UPDATE payment_orders SET status='expired', "
                    "decided_at=COALESCE(decided_at, ?) "
                    "WHERE status='awaiting_payment' AND expires_at<=?",
                    (now_iso, now_iso),
                )
                await db.execute(
                    "UPDATE payment_orders SET status='cancelled', decided_at=? "
                    "WHERE tenant_id=? AND status='awaiting_payment'",
                    (now_iso, tenant_id),
                )

                cursor = await db.execute(
                    "SELECT amount FROM payment_orders WHERE created_at>=?",
                    (reservation_cutoff,),
                )
                reserved = {int(row[0]) for row in await cursor.fetchall()}

                offsets = [
                    offset
                    for offset in range(1, _PAYMENT_OFFSET_MAX + 1)
                    if (base_amount + offset) % 10 in _JANOBHR_AMOUNT_LAST_DIGITS
                ]
                random.shuffle(offsets)
                amount = next(
                    (base_amount + offset for offset in offsets if base_amount + offset not in reserved),
                    None,
                )
                if amount is None:
                    await db.rollback()
                    raise RuntimeError(
                        "Janob HR uchun 24 soatlik noyob to'lov summalari band."
                    )

                order_code = _new_order_code()
                cursor = await db.execute(
                    "INSERT INTO payment_orders "
                    "(tenant_id, order_code, base_amount, amount, plan_code, billing_months, "
                    "status, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_payment', ?, ?)",
                    (
                        tenant_id,
                        order_code,
                        base_amount,
                        amount,
                        plan_code,
                        billing_months,
                        now_iso,
                        expires_at,
                    ),
                )
                await db.commit()
                return {
                    "id": cursor.lastrowid,
                    "order_code": order_code,
                    "amount": amount,
                    "expires_at": expires_at,
                    "plan_code": plan_code,
                }
        except aiosqlite.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
        except aiosqlite.IntegrityError:
            if attempt == 3:
                raise
            await asyncio.sleep(0)

    raise RuntimeError("To'lov buyurtmasini yaratib bo'lmadi")


'''
    text = text[:start] + new_block + text[end:]

    old_candidates = """    candidates = await database.get_open_payment_orders_by_amount(amount)\n\n    if not candidates:\n        if notify_no_match:\n"""
    new_candidates = """    await _expire_stale_payment_orders()\n    candidates = await database.get_open_payment_orders_by_amount(amount)\n\n    if not candidates:\n        late = await _handle_late_or_duplicate_payment(amount, notify_founders)\n        if late is not None:\n            return late\n        if notify_no_match:\n"""
    text = replace_once(text, old_candidates, new_candidates, label="payment late handling")
    write(path, text)


def patch_ai_scoring() -> None:
    path = "services/ai_scoring.py"
    text = read(path)
    start = text.index("async def _call_ai(system_prompt: str, user_prompt: str, max_tokens: int) -> str | None:")
    end = text.index("\n\nclass ScoreResult", start)
    new_call = '''async def _call_ai(system_prompt: str, user_prompt: str, max_tokens: int) -> str | None:
    """Race configured providers and retry truncated reasoning-model outputs once."""
    active = [(k, b, m, label) for k, b, m, label in _PROVIDERS if k]
    if not active:
        return None

    timeout = aiohttp.ClientTimeout(total=8.0, connect=2.0, sock_read=7.5)
    initial_budget = max(max_tokens, 384)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def run_provider(provider, delay: float) -> str | None:
            key, base, model, label = provider
            if delay:
                await asyncio.sleep(delay)

            async def request_once(token_budget: int) -> tuple[str | None, str | None]:
                payload = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0,
                    "max_tokens": token_budget,
                }
                async with session.post(
                    f"{base.rstrip('/')}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {key}"},
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "AI provayder (%s) xatosi: HTTP %s | %s",
                            label,
                            resp.status,
                            body[:300],
                        )
                        return None, None
                    data = await resp.json()
                    choice = data.get("choices", [{}])[0]
                    content = (choice.get("message") or {}).get("content")
                    return (content.strip() if content and content.strip() else None), choice.get(
                        "finish_reason"
                    )

            try:
                content, finish_reason = await request_once(initial_budget)
                if finish_reason == "length":
                    retry_budget = max(initial_budget * 2, 1200)
                    logger.warning(
                        "AI provayder (%s) output limitga urildi; %s token bilan qayta uriniladi.",
                        label,
                        retry_budget,
                    )
                    retry_content, retry_reason = await request_once(retry_budget)
                    if retry_content:
                        content = retry_content
                        finish_reason = retry_reason

                if not content:
                    logger.warning(
                        "AI provayder (%s) bo'sh javob qaytardi (finish_reason=%s).",
                        label,
                        finish_reason,
                    )
                    return None
                return content
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                logger.warning("AI provayder (%s) timeout bilan javob bermadi.", label)
                return None
            except Exception:
                logger.exception("AI provayder (%s) so'rovi muvaffaqiyatsiz tugadi.", label)
                return None

        tasks = [
            asyncio.create_task(run_provider(provider, idx * 1.2))
            for idx, provider in enumerate(active)
        ]
        pending = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, return_when=asyncio.FIRST_COMPLETED
                )
                for task in done:
                    result = task.result()
                    if result:
                        for other in pending:
                            other.cancel()
                        if pending:
                            await asyncio.gather(*pending, return_exceptions=True)
                        return result
            logger.error("Barcha AI provayderlar ishlamadi (%d ta sinaldi).", len(active))
            return None
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
'''
    text = text[:start] + new_call + text[end:]
    write(path, text)


def add_backup_service() -> None:
    path = Path("services/backup.py")
    content = '''"""Verified periodic SQLite backups on the persistent disk."""

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services import database

logger = logging.getLogger("janob_hr_bot")

BACKUP_INTERVAL_SECONDS = max(3600, int(os.getenv("DB_BACKUP_INTERVAL_SECONDS", "86400")))
BACKUP_RETENTION = max(2, int(os.getenv("DB_BACKUP_RETENTION", "7")))
MIN_BACKUP_GAP_SECONDS = max(1800, int(os.getenv("DB_BACKUP_MIN_GAP_SECONDS", "21600")))
_REQUIRED_TABLES = {"tenants", "applications", "vacancies", "payment_orders", "fsm_storage"}


def _validate_backup(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = _REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"Backupda jadvallar yetishmaydi: {sorted(missing)}")
        # A real read from the restored copy catches malformed/corrupt schema pages.
        connection.execute("SELECT COUNT(*) FROM tenants").fetchone()
        connection.execute("SELECT COUNT(*) FROM payment_orders").fetchone()
    finally:
        connection.close()


def create_verified_backup() -> Path | None:
    source = Path(database.SQLITE_PATH)
    if not source.exists():
        return None

    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(backup_dir.glob("data-*.sqlite3"), key=lambda p: p.stat().st_mtime)
    now_ts = datetime.now(timezone.utc).timestamp()
    if existing and now_ts - existing[-1].stat().st_mtime < MIN_BACKUP_GAP_SECONDS:
        _validate_backup(existing[-1])
        return existing[-1]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"data-{stamp}.sqlite3"
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    try:
        _validate_backup(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    existing = sorted(backup_dir.glob("data-*.sqlite3"), key=lambda p: p.stat().st_mtime)
    for old in existing[:-BACKUP_RETENTION]:
        old.unlink(missing_ok=True)
    logger.info("SQLite backup yaratildi va restore-read tekshirildi: %s", destination.name)
    return destination


async def run_backups_forever() -> None:
    while True:
        try:
            await asyncio.to_thread(create_verified_backup)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SQLite backup yaratish/tekshirishda xato.")
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
'''
    path.write_text(content, encoding="utf-8")


def patch_tests_workflow() -> None:
    path = ".github/workflows/tests.yml"
    text = read(path)
    text = replace_once(
        text,
        "    branches: [multi-tenant]\n",
        "    branches: [multi-tenant, release-hardening-2026-09-03]\n",
        label="tests hardening branch",
    )
    text = replace_once(
        text,
        "# Runs on every production branch update and can also be started manually.\n",
        "# Runs on production and release-hardening updates; production is advanced only after green tests.\n",
        label="tests workflow comment",
    )
    write(path, text)


def patch_env_example() -> None:
    path = ".env.example"
    text = read(path)
    if "WEBHOOK_ROUTING_SECRET=" not in text:
        text += "\n# Dedicated HMAC master secret for opaque Telegram webhook routes.\nWEBHOOK_ROUTING_SECRET=\nDB_BACKUP_INTERVAL_SECONDS=86400\nDB_BACKUP_RETENTION=7\nDB_BACKUP_MIN_GAP_SECONDS=21600\n"
    write(path, text)


def add_tests() -> None:
    path = Path("tests/test_release_hardening.py")
    content = '''import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import database
from services.backup import create_verified_backup
from services.payment_automation import create_payment_order
from services.tenant_activation import activate_tenant


class ReleaseHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "hardening.db")
        self.db_patch = patch.object(database, "SQLITE_PATH", self.db_path)
        self.db_patch.start()
        await database.init_db()
        self.tenant_a = await database.create_tenant(
            "Tenant A", "candidate-a", "admin-a", [101]
        )
        self.tenant_b = await database.create_tenant(
            "Tenant B", "candidate-b", "admin-b", [202]
        )

    async def asyncTearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    async def test_parallel_orders_never_share_exact_amount(self):
        first, second = await asyncio.gather(
            create_payment_order(self.tenant_a, 599_000, plan_code="growth"),
            create_payment_order(self.tenant_b, 599_000, plan_code="growth"),
        )
        self.assertNotEqual(first["amount"], second["amount"])

    async def test_expired_amount_stays_reserved_for_late_payment_window(self):
        first = await create_payment_order(self.tenant_a, 599_000, plan_code="growth")
        async with __import__("aiosqlite").connect(self.db_path) as db:
            await db.execute(
                "UPDATE payment_orders SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?",
                (first["id"],),
            )
            await db.commit()
        second = await create_payment_order(self.tenant_b, 599_000, plan_code="growth")
        self.assertNotEqual(first["amount"], second["amount"])

    async def test_failed_miniapp_provisioning_does_not_mark_pending_tenant_active(self):
        tenant = {
            "id": 77,
            "status": "pending",
            "bot_token": "candidate-token",
            "admin_bot_token": "admin-token",
            "admin_user_ids": [1],
            "bot_username": None,
        }
        update_status = AsyncMock()
        with (
            patch("services.tenant_activation.database.get_tenant", AsyncMock(return_value=tenant)),
            patch("webhook_app.register_new_tenant_webhook", AsyncMock(side_effect=["candidate_bot", "admin_bot"])),
            patch("webhook_app.configure_admin_miniapp", AsyncMock(side_effect=RuntimeError("boom"))),
            patch("services.tenant_activation.database.update_tenant_status", update_status),
        ):
            result = await activate_tenant(77)
        self.assertFalse(result["ok"])
        update_status.assert_not_awaited()

    async def test_backup_is_readable_restored_copy(self):
        backup = await asyncio.to_thread(create_verified_backup)
        self.assertIsNotNone(backup)
        self.assertTrue(Path(backup).exists())

    def test_webhook_source_never_uses_bot_token_in_route(self):
        source = Path("webhook_app.py").read_text(encoding="utf-8")
        self.assertNotIn("/webhook/{bot_token}", source)
        self.assertNotIn("TokenBasedRequestHandler", source)
        self.assertIn("secret_token=telegram_secret", source)
        self.assertIn("/telegram/{webhook_id}", source)


if __name__ == "__main__":
    unittest.main()
'''
    path.write_text(content, encoding="utf-8")


def main() -> None:
    patch_config()
    patch_webhook_app()
    patch_tenant_activation()
    patch_payment_automation()
    patch_ai_scoring()
    add_backup_service()
    patch_tests_workflow()
    patch_env_example()
    add_tests()


if __name__ == "__main__":
    main()
