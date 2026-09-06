"""Partner Mini App routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from services import partner_database as pdb

BASE_DIR = Path(__file__).resolve().parent
PARTNER_MINIAPP_DIR = BASE_DIR / "partner_miniapp"
JANOBHR_MAIN_BOT_USERNAME = os.getenv("JANOBHR_MAIN_BOT_USERNAME", "janobHR_bot").strip().lstrip("@")
PARTNER_BOT_TOKEN = os.getenv("PARTNER_BOT_TOKEN", "").strip()
INIT_DATA_MAX_AGE = 24 * 60 * 60


def _telegram_user_from_init_data(init_data: str) -> dict | None:
    """Validate Telegram WebApp initData and return its user payload."""
    if not init_data or not PARTNER_BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
        secret_key = hmac.new(
            b"WebAppData", PARTNER_BOT_TOKEN.encode(), hashlib.sha256
        ).digest()
        expected_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(received_hash, expected_hash):
            return None

        auth_date = int(pairs.get("auth_date") or 0)
        now = int(time.time())
        if auth_date <= 0 or auth_date > now + 60 or now - auth_date > INIT_DATA_MAX_AGE:
            return None

        user = json.loads(pairs.get("user") or "{}")
        if not isinstance(user, dict) or not user.get("id"):
            return None
        return user
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


async def partner_miniapp_page(request: web.Request) -> web.Response:
    index_path = PARTNER_MINIAPP_DIR / "index.html"
    if not index_path.exists():
        raise web.HTTPNotFound(text="Partner Mini App topilmadi")
    return web.FileResponse(index_path)


async def partner_stats(request: web.Request) -> web.Response:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    tg_user = _telegram_user_from_init_data(init_data)
    if not tg_user:
        return web.json_response({"ok": False, "error": "invalid_telegram_auth"}, status=401)

    try:
        user_id = int(tg_user["id"])
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "invalid_user"}, status=400)

    partner = await pdb.get_partner_by_user_id(user_id)
    if not partner or partner.get("status") != "approved":
        return web.json_response({"ok": False, "error": "partner_not_approved"}, status=403)

    stats = await pdb.get_partner_stats(partner["id"])
    referral_link = ""
    if partner.get("referral_code"):
        referral_link = f"https://t.me/{JANOBHR_MAIN_BOT_USERNAME}?start=ref_{partner['referral_code']}"

    return web.json_response(
        {
            "ok": True,
            "partner": {
                "id": partner["id"],
                "full_name": partner.get("full_name") or "Hamkor",
                "username": partner.get("username") or "",
                "referral_code": partner.get("referral_code") or "",
            },
            "referral_link": referral_link,
            "stats": {
                **stats,
                "earned_label": pdb.format_uzs(stats.get("earned", 0)),
            },
        }
    )


def register_partner_miniapp(app: web.Application) -> None:
    app.router.add_static(
        "/partner-miniapp-assets/",
        path=str(PARTNER_MINIAPP_DIR),
        name="partner_miniapp_assets",
    )
    app.router.add_get("/partner", partner_miniapp_page)
    app.router.add_get("/partner/", partner_miniapp_page)
    app.router.add_get("/api/partner-miniapp/stats", partner_stats)
