"""Janob HR founder-only Telegram Mini App API."""

from pathlib import Path

from aiohttp import web

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS
from miniapp_api import verify_init_data
from services import database

STATIC_DIR = Path(__file__).with_name("founder_miniapp")


def _authorize_founder(request: web.Request) -> dict:
    if not FOUNDER_BOT_TOKEN:
        raise web.HTTPNotFound()
    auth = verify_init_data(
        request.headers.get("X-Telegram-Init-Data", ""), FOUNDER_BOT_TOKEN
    )
    if auth["user_id"] not in FOUNDER_USER_IDS:
        raise web.HTTPForbidden(text="Founder paneliga kirish huquqingiz yo'q.")
    return auth


async def founder_index(request: web.Request) -> web.Response:
    return web.Response(
        text=(STATIC_DIR / "index.html").read_text(encoding="utf-8"),
        content_type="text/html",
    )


async def founder_dashboard(request: web.Request) -> web.Response:
    _authorize_founder(request)
    return web.json_response(await database.get_founder_dashboard_data())


def register_founder_miniapp(app: web.Application) -> None:
    app.router.add_get("/founder", founder_index)
    app.router.add_static(
        "/founder-assets", STATIC_DIR, show_index=False, append_version=True
    )
    app.router.add_get("/api/founder/dashboard", founder_dashboard)
