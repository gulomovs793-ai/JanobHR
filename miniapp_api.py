"""Janob HR Telegram Mini App API.

Har bir so'rov Telegram WebApp initData imzosi bilan tekshiriladi. Tenant ID
URLda bo'lsa ham unga ishonilmaydi: foydalanuvchi aynan shu tenantning admini
ekanligi bazadan qayta tekshiriladi.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram import Bot
from aiohttp import web

from handlers.sell import send_slot_offer
from i18n import DEFAULT_LANG, t
from services import database
from services.ai_scoring import aggregate_scores
from services.plans import PUBLIC_PLAN_CODES, get_plan

logger = logging.getLogger("janob_hr_bot")
STATIC_DIR = Path(__file__).with_name("miniapp")
MAX_AUTH_AGE_SECONDS = 60 * 60
RATE_LIMIT = 120
_requests: dict[tuple[int, int], deque[float]] = defaultdict(deque)


def verify_init_data(init_data: str, bot_token: str, *, now: int | None = None) -> dict:
    """Telegram initData imzosini va eskirmaganini tekshiradi."""
    if not init_data or len(init_data) > 8192:
        raise web.HTTPUnauthorized(text="Telegram orqali qayta oching.")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise web.HTTPUnauthorized(text="Telegram imzosi topilmadi.")
    check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected):
        raise web.HTTPUnauthorized(text="Telegram imzosi noto'g'ri.")
    try:
        auth_date = int(pairs["auth_date"])
        user = json.loads(pairs["user"])
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise web.HTTPUnauthorized(text="Telegram ma'lumoti to'liq emas.")
    current = int(time.time()) if now is None else now
    if auth_date > current + 30 or current - auth_date > MAX_AUTH_AGE_SECONDS:
        raise web.HTTPUnauthorized(text="Sessiya eskirgan. Mini Appni qayta oching.")
    return {"user_id": user_id, "user": user, "auth_date": auth_date}


@web.middleware
async def security_headers(request: web.Request, handler):
    response = await handler(request)
    response.headers.update(
        {
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
            "Content-Security-Policy": (
                "default-src 'self'; script-src 'self' https://telegram.org; "
                "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                "frame-ancestors https://web.telegram.org https://*.telegram.org"
            ),
        }
    )
    return response


async def _authorize(request: web.Request) -> tuple[dict, dict]:
    try:
        tenant_id = int(request.match_info["tenant_id"])
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    tenant = await database.get_tenant(tenant_id)
    if (
        not tenant
        or tenant.get("status") != "active"
        or not tenant.get("admin_bot_token")
    ):
        raise web.HTTPNotFound()
    auth = verify_init_data(
        request.headers.get("X-Telegram-Init-Data", ""), tenant["admin_bot_token"]
    )
    if auth["user_id"] not in tenant.get("admin_user_ids", []):
        raise web.HTTPForbidden(text="Bu kompaniya paneliga kirish huquqingiz yo'q.")
    key = (tenant_id, auth["user_id"])
    bucket = _requests[key]
    cutoff = time.monotonic() - 60
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT:
        raise web.HTTPTooManyRequests(
            text="Juda ko'p so'rov. Birozdan keyin urinib ko'ring."
        )
    bucket.append(time.monotonic())
    return tenant, auth


def _candidate_summary(app: dict) -> dict:
    aggregate = aggregate_scores(app.get("ai_scores") or {})
    return {
        "id": app["id"],
        "full_name": app["full_name"],
        "username": app.get("username"),
        "phone_number": app.get("phone_number"),
        "vacancy_key": app["vacancy_key"],
        "vacancy_title": app["vacancy_title"],
        "status": app["status"],
        "score": aggregate["avg_score"] if aggregate else None,
        "selected_slot": app.get("selected_slot"),
        "created_at": app["created_at"],
    }


async def index(request: web.Request):
    tenant_id = request.match_info["tenant_id"]
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return web.Response(
        text=html.replace("__TENANT_ID__", tenant_id), content_type="text/html"
    )


async def dashboard(request: web.Request):
    tenant, _ = await _authorize(request)
    stats = await database.get_overall_stats(tenant["id"])
    usage = await database.get_subscription_usage(tenant["id"])
    vacancies = await database.list_vacancies(tenant["id"], active_only=False)
    apps, _ = await database.list_applications(tenant["id"], limit=5)
    plan = usage["plan"]
    return web.json_response(
        {
            "company": tenant["company_name"],
            "stats": stats,
            "recent": [_candidate_summary(app) for app in apps],
            "active_vacancies": sum(1 for item in vacancies if item["active"]),
            "billing": {
                "plan": plan.name,
                "plan_code": plan.code,
                "applications_used": usage["applications_used"],
                "applications_limit": plan.application_limit,
                "vacancies_used": usage["vacancies_used"],
                "vacancies_limit": plan.vacancy_limit,
                "expires_at": usage["expires_at"],
            },
        }
    )


async def candidates(request: web.Request):
    tenant, _ = await _authorize(request)
    status = request.query.get("status") or None
    if status == "all":
        status = None
    allowed = {None, "pending", "saved", "accepted", "declined"}
    if status not in allowed:
        raise web.HTTPBadRequest(text="Noto'g'ri status.")
    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        raise web.HTTPBadRequest(text="Noto'g'ri sahifa.")
    limit = 20
    apps, total = await database.list_applications(
        tenant["id"], status=status, limit=limit, offset=page * limit
    )
    return web.json_response(
        {
            "items": [_candidate_summary(app) for app in apps],
            "total": total,
            "page": page,
        }
    )


async def candidate_detail(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        app_id = int(request.match_info["app_id"])
    except ValueError:
        raise web.HTTPNotFound()
    app = await database.get_application(tenant["id"], app_id)
    if not app:
        raise web.HTTPNotFound(text="Nomzod topilmadi.")
    result = _candidate_summary(app)
    result.update(
        {
            "answers": app.get("answers") or {},
            "ai_scores": app.get("ai_scores") or {},
            "suspect_flags": app.get("ai_suspect_flags") or [],
            "has_resume": bool(app.get("resume_file_id")),
            "has_voice": bool(app.get("voice_answers")),
        }
    )
    return web.json_response(result)


async def candidate_decision(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        app_id = int(request.match_info["app_id"])
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="Noto'g'ri so'rov.")
    action = body.get("action")
    if action not in {"accept", "save", "reject"}:
        raise web.HTTPBadRequest(text="Noto'g'ri qaror.")
    app = await database.get_application(tenant["id"], app_id)
    if not app:
        raise web.HTTPNotFound(text="Nomzod topilmadi.")
    if app["status"] not in {"pending", "saved"}:
        raise web.HTTPConflict(text="Bu nomzod bo'yicha qaror qabul qilingan.")
    new_status = {"accept": "accepted", "save": "saved", "reject": "declined"}[action]
    await database.update_status(tenant["id"], app_id, new_status)
    if action != "save":
        bot = Bot(token=tenant["bot_token"])
        try:
            if action == "accept":
                await send_slot_offer(
                    bot,
                    tenant["id"],
                    app["user_id"],
                    app_id,
                    t("decision_accept_intro", app.get("lang", DEFAULT_LANG)),
                    app.get("lang", DEFAULT_LANG),
                )
            else:
                await bot.send_message(
                    app["user_id"],
                    t("decision_decline_text", app.get("lang", DEFAULT_LANG)),
                )
        except Exception:
            logger.exception("Mini App qarori yuborilmadi (app_id=%s)", app_id)
            return web.json_response(
                {
                    "ok": True,
                    "status": new_status,
                    "warning": "Qaror saqlandi, lekin nomzodga xabar yuborilmadi.",
                }
            )
        finally:
            await bot.session.close()
    return web.json_response({"ok": True, "status": new_status})


async def vacancies(request: web.Request):
    tenant, _ = await _authorize(request)
    items = await database.list_vacancies(tenant["id"], active_only=False)
    stats = {
        item["vacancy_key"]: item
        for item in await database.get_vacancy_stats(tenant["id"])
    }
    result = []
    for item in items:
        stat = stats.get(item["key"], {})
        result.append(
            {
                "key": item["key"],
                "title": item["title"],
                "active": item["active"],
                "questions": len(item["questions"]),
                "total": stat.get("total", 0),
                "pending": stat.get("pending", 0),
            }
        )
    return web.json_response({"items": result})


async def toggle_vacancy(request: web.Request):
    tenant, _ = await _authorize(request)
    key = request.match_info["vacancy_key"]
    vacancy = await database.get_vacancy(tenant["id"], key)
    if not vacancy:
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    await database.update_vacancy(tenant["id"], key, active=not vacancy["active"])
    return web.json_response({"ok": True, "active": not vacancy["active"]})


async def billing(request: web.Request):
    tenant, _ = await _authorize(request)
    usage = await database.get_subscription_usage(tenant["id"])
    return web.json_response(
        {
            "current": {
                "code": usage["plan"].code,
                "name": usage["plan"].name,
                "expires_at": usage["expires_at"],
            },
            "plans": [
                {
                    "code": code,
                    "name": get_plan(code).name,
                    "price": get_plan(code).price,
                    "applications": get_plan(code).application_limit,
                    "vacancies": get_plan(code).vacancy_limit,
                }
                for code in PUBLIC_PLAN_CODES
            ],
        }
    )


def register_miniapp(app: web.Application) -> None:
    app.middlewares.append(security_headers)
    app.router.add_get("/miniapp/{tenant_id}", index)
    app.router.add_static(
        "/miniapp-assets", STATIC_DIR, show_index=False, append_version=True
    )
    app.router.add_get("/api/miniapp/{tenant_id}/dashboard", dashboard)
    app.router.add_get("/api/miniapp/{tenant_id}/candidates", candidates)
    app.router.add_get("/api/miniapp/{tenant_id}/candidates/{app_id}", candidate_detail)
    app.router.add_post(
        "/api/miniapp/{tenant_id}/candidates/{app_id}/decision", candidate_decision
    )
    app.router.add_get("/api/miniapp/{tenant_id}/vacancies", vacancies)
    app.router.add_post(
        "/api/miniapp/{tenant_id}/vacancies/{vacancy_key}/toggle", toggle_vacancy
    )
    app.router.add_get("/api/miniapp/{tenant_id}/billing", billing)
