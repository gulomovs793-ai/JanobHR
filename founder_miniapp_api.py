"""Janob HR founder-only Telegram Mini App API."""

from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from aiohttp import web

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS, SQLITE_PATH
from miniapp_api import verify_init_data
from services import database

STATIC_DIR = Path(__file__).with_name("founder_miniapp")
_TEST_REVENUE_RESET_KEY = "founder_test_revenue_reset_2026_09_06"


def _authorize_founder(request: web.Request) -> dict:
    if not FOUNDER_BOT_TOKEN:
        raise web.HTTPNotFound()
    auth = verify_init_data(
        request.headers.get("X-Telegram-Init-Data", ""), FOUNDER_BOT_TOKEN
    )
    if auth["user_id"] not in FOUNDER_USER_IDS:
        raise web.HTTPForbidden(text="Founder paneliga kirish huquqingiz yo'q.")
    return auth


async def _reset_test_revenue_once() -> None:
    """Oldingi test davrida approved qilingan soxta tushumlarni bir marta tozalaydi.

    Haqiqiy kelajak to'lovlariga tegmaydi: reset marker yozilgach bu migratsiya
    boshqa ishga tushmaydi. Eski test orderlar tarixdan o'chmaydi, cancelled
    holatiga o'tadi, shuning uchun Founder revenue hisoblari 0 dan boshlanadi.
    """
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT 1 FROM system_notifications WHERE notification_key=? LIMIT 1",
                (_TEST_REVENUE_RESET_KEY,),
            )
            if await cursor.fetchone():
                await db.commit()
                return

            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                "UPDATE payment_orders "
                "SET status='cancelled', "
                "notification_text=COALESCE(notification_text, '') || ? "
                "WHERE status='approved'",
                (" [TEST REVENUE RESET]",),
            )
            await db.execute(
                "INSERT INTO system_notifications(notification_key, sent_at) VALUES (?, ?)",
                (_TEST_REVENUE_RESET_KEY, now),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def founder_index(request: web.Request) -> web.Response:
    return web.Response(
        text=(STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        content_type="text/html",
    )


async def founder_dashboard(request: web.Request) -> web.Response:
    _authorize_founder(request)
    await _reset_test_revenue_once()
    return web.json_response(await database.get_founder_dashboard_data())


def register_founder_miniapp(app: web.Application) -> None:
    app.router.add_get("/founder", founder_index)
    app.router.add_static(
        "/founder-assets", STATIC_DIR, show_index=False, append_version=True
    )
    app.router.add_get("/api/founder/dashboard", founder_dashboard)
