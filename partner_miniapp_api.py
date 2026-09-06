"""Partner Mini App routes."""

from __future__ import annotations

import os
from pathlib import Path

from aiohttp import web

from services import partner_database as pdb

BASE_DIR = Path(__file__).resolve().parent
PARTNER_MINIAPP_DIR = BASE_DIR / "partner_miniapp"
JANOBHR_MAIN_BOT_USERNAME = os.getenv("JANOBHR_MAIN_BOT_USERNAME", "janobHR_bot").strip().lstrip("@")


async def partner_miniapp_page(request: web.Request) -> web.Response:
    index_path = PARTNER_MINIAPP_DIR / "index.html"
    if not index_path.exists():
        raise web.HTTPNotFound(text="Partner Mini App topilmadi")
    return web.FileResponse(index_path)


async def partner_stats(request: web.Request) -> web.Response:
    raw_user_id = (request.query.get("user_id") or "").strip()
    try:
        user_id = int(raw_user_id)
    except ValueError:
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
