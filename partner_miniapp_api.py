"""Partner Mini App routes."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl

import aiosqlite
from aiohttp import web

from partner_payout_bot import notify_founders_about_payout
from services import partner_database as pdb
from services import partner_payouts
from services.partner_links import build_referral_link, resolve_main_bot_username
from services.plans import PUBLIC_PLAN_CODES

BASE_DIR = Path(__file__).resolve().parent
PARTNER_MINIAPP_DIR = BASE_DIR / "partner_miniapp"
PARTNER_BOT_TOKEN = os.getenv("PARTNER_BOT_TOKEN", "").strip()
INIT_DATA_MAX_AGE = 24 * 60 * 60
logger = logging.getLogger("janob_hr_partner")


def _telegram_user_from_init_data(init_data: str) -> dict | None:
    if not init_data or not PARTNER_BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", "")
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
        secret_key = hmac.new(b"WebAppData", PARTNER_BOT_TOKEN.encode(), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received_hash, expected_hash):
            return None
        auth_date = int(pairs.get("auth_date") or 0)
        now = int(time.time())
        if auth_date <= 0 or auth_date > now + 60 or now - auth_date > INIT_DATA_MAX_AGE:
            return None
        user = json.loads(pairs.get("user") or "{}")
        return user if isinstance(user, dict) and user.get("id") else None
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


async def _approved_partner(request: web.Request) -> tuple[dict | None, web.Response | None]:
    tg_user = _telegram_user_from_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if not tg_user:
        return None, web.json_response({"ok": False, "error": "invalid_telegram_auth"}, status=401)
    try:
        user_id = int(tg_user["id"])
    except (TypeError, ValueError):
        return None, web.json_response({"ok": False, "error": "invalid_user"}, status=400)
    partner = await pdb.get_partner_by_user_id(user_id)
    if not partner or partner.get("status") != "approved":
        return None, web.json_response({"ok": False, "error": "partner_not_approved"}, status=403)
    return partner, None


def _public_payout(request: dict | None) -> dict | None:
    """Return payout state without sending a full card number to the browser."""
    if not request:
        return None
    card = str(request.get("payout_card_number") or "")
    return {
        "id": request.get("id"),
        "status": request.get("status"),
        "requested_amount": int(request.get("requested_amount") or 0),
        "bonus_amount": int(request.get("bonus_amount") or 0),
        "total_amount": int(request.get("total_amount") or 0),
        "payout_due_date": request.get("payout_due_date"),
        "requested_at": request.get("requested_at"),
        "payout_full_name": request.get("payout_full_name") or "",
        "receipt_telegram_username": request.get("receipt_telegram_username") or "",
        "payout_card_masked": f"**** {card[-4:]}" if len(card) >= 4 else "",
        "delay_days": int(request.get("delay_days") or 0),
    }


async def partner_miniapp_page(request: web.Request) -> web.Response:
    index_path = PARTNER_MINIAPP_DIR / "index.html"
    if not index_path.exists():
        raise web.HTTPNotFound(text="Partner Mini App topilmadi")
    return web.FileResponse(index_path, headers={"Cache-Control": "no-store"})


async def partner_stats(request: web.Request) -> web.Response:
    partner, error = await _approved_partner(request)
    if error:
        return error
    stats = await pdb.get_partner_stats(partner["id"])
    balance = await partner_payouts.get_partner_balance(partner["id"])
    balance["active_request"] = _public_payout(balance.get("active_request"))
    balance["next_payout_date"] = (
        (balance.get("active_request") or {}).get("payout_due_date")
        if balance.get("active_request")
        else partner_payouts.next_payout_date().isoformat()
    )
    referral_target = await resolve_main_bot_username()
    referral_link = build_referral_link(referral_target, partner.get("referral_code"))

    promo = None
    try:
        from config import SQLITE_PATH

        async with aiosqlite.connect(SQLITE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT code, discount_percent, discount_type, discount_value, "
                "expires_at, plan_code FROM partner_promo_codes "
                "WHERE partner_id=? AND status='active' "
                "AND (expires_at IS NULL OR expires_at > ?) "
                "ORDER BY id DESC LIMIT 1",
                (partner["id"], datetime.now(timezone.utc).isoformat()),
            )
            row = await cur.fetchone()
            promo = dict(row) if row else None
    except aiosqlite.Error:
        promo = None

    return web.json_response({
        "ok": True,
        "partner": {"id": partner["id"], "full_name": partner.get("full_name") or "Hamkor", "username": partner.get("username") or "", "referral_code": partner.get("referral_code") or ""},
        "referral_link": referral_link,
        "promo": promo,
        "promo_caps": {
            plan_code: {
                "percent": pdb.max_promo_percent(plan_code),
                "amount": pdb.max_promo_amount(plan_code),
            }
            for plan_code in ("all", *PUBLIC_PLAN_CODES)
        },
        "stats": {**stats, "earned_label": pdb.format_uzs(stats.get("earned", 0))},
        "balance": {
            **balance,
            "earned_label": pdb.format_uzs(balance.get("earned", 0)),
            "available_label": pdb.format_uzs(balance.get("available", 0)),
            "reserved_label": pdb.format_uzs(balance.get("reserved", 0)),
            "paid_label": pdb.format_uzs(balance.get("paid", 0)),
        },
        "activity": await pdb.get_partner_activity(partner["id"]),
        "leads": await pdb.get_partner_leads(partner["id"]),
    })


async def partner_promo(request: web.Request) -> web.Response:
    partner, error = await _approved_partner(request)
    if error:
        return error
    try:
        payload = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"ok": False, "error": "invalid_discount"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "invalid_discount"}, status=400)
    try:
        discount_type = str(payload.get("discount_type") or "percent").strip().lower()
        discount = int(payload.get("discount_value"))
        duration_days = int(payload.get("duration_days"))
        plan_code = str(payload.get("plan_code") or "all").strip().lower()
        if (
            discount_type not in {"percent", "amount"}
            or discount < 0
            or (discount_type == "amount" and discount == 0)
            or duration_days < 1
            or duration_days > 365
        ):
            raise ValueError
        if plan_code != "all" and plan_code not in PUBLIC_PLAN_CODES:
            raise ValueError
        if discount_type == "percent" and discount > pdb.max_promo_percent(plan_code):
            raise ValueError
        if discount_type == "amount" and discount > pdb.max_promo_amount(plan_code):
            raise ValueError
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "error": "invalid_discount"}, status=400)

    try:
        promo = await pdb.create_or_update_promo_code(partner["id"], discount, discount_type=discount_type, duration_days=duration_days, plan_code=plan_code)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    if not promo:
        return web.json_response({"ok": False, "error": "promo_not_created"}, status=400)

    payouts = {}
    plans_to_show = PUBLIC_PLAN_CODES if plan_code == "all" else (plan_code,)
    for plan in plans_to_show:
        calc = pdb.calculate_partner_payout(plan, discount if discount_type == "percent" else 0, discount_type=discount_type, discount_value=discount)
        payouts[plan] = pdb.format_uzs(calc["commission_amount"])

    return web.json_response(
        {
            "ok": True,
            "promo": {
                "code": promo["code"],
                "discount_type": promo["discount_type"],
                "discount_value": promo["discount_value"],
                "discount_percent": promo["discount_percent"],
                "expires_at": promo["expires_at"],
                "plan_code": promo.get("plan_code") or "all",
            },
            "payouts": payouts,
        }
    )


async def partner_payout(request: web.Request) -> web.Response:
    """Create one payout request for the authenticated partner."""
    partner, error = await _approved_partner(request)
    if error:
        return error
    try:
        payload = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"ok": False, "error": "invalid_payout"}, status=400)
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "invalid_payout"}, status=400)

    full_name = payload.get("full_name") if isinstance(payload.get("full_name"), str) else ""
    card_number = payload.get("card_number") if isinstance(payload.get("card_number"), str) else ""
    receipt_username = (
        payload.get("receipt_username")
        if isinstance(payload.get("receipt_username"), str)
        else ""
    )
    _, _, _, validation_error = partner_payouts.validate_payout_details(
        full_name, card_number, receipt_username
    )
    if validation_error:
        return web.json_response({"ok": False, "error": validation_error}, status=400)

    try:
        result = await partner_payouts.create_payout_request(
            int(partner["id"]), full_name, card_number, receipt_username
        )
    except aiosqlite.Error:
        logger.exception("Mini App payout arizasi bazaga yozilmadi")
        return web.json_response(
            {"ok": False, "error": "Payout vaqtincha mavjud emas. Qayta urinib ko'ring."},
            status=503,
        )
    if not result.get("ok"):
        status = 409 if "hali yopilmagan" in str(result.get("error") or "") else 400
        return web.json_response(
            {"ok": False, "error": result.get("error") or "Payout arizasi yaratilmadi."},
            status=status,
        )

    founder_notified = False
    try:
        founder_notified = await notify_founders_about_payout(
            result, title="💸 Hamkor pul yechish arizasi"
        )
        if founder_notified:
            await partner_payouts.mark_payout_notified(int(result["id"]), first=True)
    except Exception:
        logger.exception("Mini App payout notification yuborilmadi: %s", result.get("id"))

    return web.json_response(
        {
            "ok": True,
            "payout": _public_payout(result),
        },
        status=201,
    )


def register_partner_miniapp(app: web.Application) -> None:
    app.router.add_static("/partner-miniapp-assets/", path=str(PARTNER_MINIAPP_DIR), name="partner_miniapp_assets")
    app.router.add_get("/partner", partner_miniapp_page)
    app.router.add_get("/partner/", partner_miniapp_page)
    app.router.add_get("/api/partner-miniapp/stats", partner_stats)
    app.router.add_post("/api/partner-miniapp/promo", partner_promo)
    app.router.add_post("/api/partner-miniapp/payout", partner_payout)
