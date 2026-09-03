"""Janob HR Telegram Mini App API.

Har bir so'rov Telegram WebApp initData imzosi bilan tekshiriladi. Tenant ID
URLda bo'lsa ham unga ishonilmaydi: foydalanuvchi aynan shu tenantning admini
ekanligi bazadan qayta tekshiriladi.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote

from aiogram import Bot
from aiohttp import web
from openpyxl import Workbook
from openpyxl.styles import Font

from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER, WEBHOOK_BASE_URL
from handlers.sell import send_slot_offer
from i18n import DEFAULT_LANG, t
from services import database
from services.ai_scoring import aggregate_scores, generate_questions
from services.candidate_followup import notify_candidate_outcome
from services.hiring_intelligence import (
    candidate_risks,
    compare_candidates,
    hiring_funnel,
)
from services.payment_automation import (
    create_payment_order as create_payment_order_for_plan,
)
from services.plans import PUBLIC_PLAN_CODES, get_plan, get_plan_transition

logger = logging.getLogger("janob_hr_bot")
STATIC_DIR = Path(__file__).with_name("miniapp")
MAX_AUTH_AGE_SECONDS = 60 * 60
RATE_LIMIT = 120
_requests: dict[tuple[int, int], deque[float]] = defaultdict(deque)
_interview_reminders: dict[tuple[int, int], float] = {}


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
                "style-src 'self' 'unsafe-inline'; "
                "font-src 'self' data:; "
                "img-src 'self' data:; connect-src 'self'; "
                "frame-ancestors https://web.telegram.org https://*.telegram.org"
            ),
        }
    )
    return response


def _request_init_data(request: web.Request) -> str:
    value = (request.headers.get("X-Telegram-Init-Data") or "").strip()
    if value:
        return value
    authorization = (request.headers.get("Authorization") or "").strip()
    if authorization.lower().startswith("tma "):
        value = authorization[4:].strip()
        if value:
            return value
    cookie = request.cookies.get("jh_tg_init") or ""
    if cookie:
        return unquote(cookie).strip()
    return ""


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
    auth = verify_init_data(_request_init_data(request), tenant["admin_bot_token"])
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
    try:
        tenant_id = str(int(request.match_info["tenant_id"]))
    except (KeyError, ValueError):
        raise web.HTTPNotFound()
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return web.Response(
        text=html.replace("__TENANT_ID__", tenant_id), content_type="text/html"
    )


async def health(request: web.Request):
    db_ok = await database.healthcheck()
    configured = bool(WEBHOOK_BASE_URL)
    payload = {
        "ok": db_ok and configured,
        "service": "janob-hr",
        "database": "ok" if db_ok else "error",
        "webhook_configured": configured,
    }
    return web.json_response(payload, status=200 if payload["ok"] else 503)


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
    search = (request.query.get("q") or "").strip()
    if len(search) > 80:
        raise web.HTTPBadRequest(text="Qidiruv matni juda uzun.")
    if status == "all":
        status = None
    allowed = {
        None,
        "pending",
        "saved",
        "accepted",
        "declined",
        "rejected_hard_filter",
        "rejected_irrelevant",
        "rejected_ai_generated",
        "hired",
        "not_hired",
        "no_show",
    }
    if status not in allowed:
        raise web.HTTPBadRequest(text="Noto'g'ri status.")
    try:
        page = max(0, int(request.query.get("page", "0")))
    except ValueError:
        raise web.HTTPBadRequest(text="Noto'g'ri sahifa.")
    limit = 20
    apps, total = await database.list_applications(
        tenant["id"], status=status, search=search or None, limit=limit, offset=page * limit
    )
    return web.json_response(
        {
            "items": [_candidate_summary(app) for app in apps],
            "total": total,
            "page": page,
        }
    )


async def interviews(request: web.Request):
    tenant, _ = await _authorize(request)
    apps, _ = await database.list_applications(
        tenant["id"], status="accepted", limit=200
    )
    scheduled = []
    awaiting_slot = []
    for app in apps:
        item = _candidate_summary(app)
        if item.get("selected_slot"):
            scheduled.append(item)
        else:
            awaiting_slot.append(item)
    slots = await database.list_interview_slots(tenant["id"], active_only=True)
    for slot in slots:
        slot["booked"] = await database.count_slot_bookings(
            tenant["id"], slot["label"]
        )
    settings = await database.get_interview_settings(tenant["id"])
    return web.json_response(
        {
            "scheduled": scheduled,
            "awaiting_slot": awaiting_slot,
            "total": len(apps),
            "slots": slots,
            "settings": settings,
        }
    )


async def add_interview_slot(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        body = await request.json()
        label = str(body.get("label") or "").strip()
        capacity = int(body.get("capacity", 1))
        starts_at = _normalise_starts_at(body.get("starts_at"))
        if not starts_at and label:
            try:
                starts_at = _normalise_starts_at(label)
            except web.HTTPBadRequest:
                starts_at = None
    except (ValueError, TypeError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="Vaqt ma'lumoti noto'g'ri.")
    if not 3 <= len(label) <= 80:
        raise web.HTTPBadRequest(text="Sana va vaqtni to'liq yozing.")
    if not 1 <= capacity <= 100:
        raise web.HTTPBadRequest(text="Sig'im 1 dan 100 gacha bo'lishi kerak.")
    existing = await database.list_interview_slots(tenant["id"], active_only=True)
    if any(item["label"].casefold() == label.casefold() for item in existing):
        raise web.HTTPConflict(text="Bu suhbat vaqti allaqachon mavjud.")
    try:
        if starts_at:
            slot_id = await database.add_interview_slot(
                tenant["id"], label, capacity, starts_at=starts_at
            )
        else:
            # Eski erkin-format slotlar ham ishlashda davom etadi.
            slot_id = await database.add_interview_slot(tenant["id"], label, capacity)
    except database.InterviewSlotConflict as exc:
        raise web.HTTPConflict(text="Bu suhbat vaqti allaqachon mavjud.") from exc
    return web.json_response(
        {
            "ok": True,
            "slot": {
                "id": slot_id, "label": label, "capacity": capacity,
                "booked": 0, "starts_at": starts_at,
            },
        }
    )


async def delete_interview_slot(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        slot_id = int(request.match_info["slot_id"])
    except ValueError:
        raise web.HTTPNotFound()
    slots = await database.list_interview_slots(tenant["id"], active_only=True)
    slot = next((item for item in slots if item["id"] == slot_id), None)
    if not slot:
        raise web.HTTPNotFound(text="Suhbat vaqti topilmadi.")
    booked = await database.count_slot_bookings(tenant["id"], slot["label"])
    if booked:
        raise web.HTTPConflict(
            text="Bu vaqtni nomzod tanlagan. Avval suhbatni boshqa vaqtga ko'chiring."
        )
    try:
        deleted = await database.delete_interview_slot(tenant["id"], slot_id)
    except database.InterviewSlotBooked as exc:
        raise web.HTTPConflict(
            text="Bu vaqtni nomzod tanlagan. Avval suhbatni boshqa vaqtga ko'chiring."
        ) from exc
    if not deleted:
        raise web.HTTPNotFound(text="Suhbat vaqti topilmadi.")
    return web.json_response({"ok": True})


async def update_interview_settings(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="Sozlamalar noto'g'ri.")
    limits = {
        "location_text": 240,
        "interviewer_name": 80,
        "interviewer_phone": 32,
        "notes": 500,
    }
    fields = {}
    for key, limit in limits.items():
        value = str(body.get(key) or "").strip()
        if len(value) > limit:
            raise web.HTTPBadRequest(text=f"{key} juda uzun.")
        fields[key] = value or None
    await database.update_interview_settings(tenant["id"], **fields)
    return web.json_response({"ok": True, "settings": fields})


async def remind_interview_candidate(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        app_id = int(request.match_info["app_id"])
    except ValueError:
        raise web.HTTPNotFound()
    app = await database.get_application(tenant["id"], app_id)
    if not app:
        raise web.HTTPNotFound(text="Nomzod topilmadi.")
    if app["status"] != "accepted" or app.get("selected_slot"):
        raise web.HTTPConflict(text="Bu nomzod uchun eslatma kerak emas.")
    key = (tenant["id"], app_id)
    last_sent = _interview_reminders.get(key, 0)
    if time.monotonic() - last_sent < 60:
        raise web.HTTPTooManyRequests(text="Eslatma yaqinda yuborilgan.")
    bot = Bot(token=tenant["bot_token"])
    try:
        sent = await send_slot_offer(
            bot,
            tenant["id"],
            app["user_id"],
            app_id,
            "Suhbat vaqtini tanlashni eslatib o'tamiz.",
            app.get("lang", DEFAULT_LANG),
        )
    finally:
        await bot.session.close()
    if not sent:
        raise web.HTTPConflict(text="Avval kamida bitta bo'sh suhbat vaqtini qo'shing.")
    _interview_reminders[key] = time.monotonic()
    return web.json_response({"ok": True})


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
    vacancy = await database.get_vacancy(tenant["id"], app["vacancy_key"])
    result.update(
        {
            "answers": app.get("answers") or {},
            "ai_scores": app.get("ai_scores") or {},
            "suspect_flags": app.get("ai_suspect_flags") or [],
            "has_resume": bool(app.get("resume_file_id")),
            "has_voice": bool(app.get("voice_answers")),
            "risk_signals": candidate_risks(app, vacancy),
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
    if action == "accept" and not await database.get_available_interview_slots(tenant["id"]):
        raise web.HTTPConflict(
            text="Avval Suhbatlar bo'limidan kamida bitta bo'sh vaqt qo'shing."
        )
    new_status = {"accept": "accepted", "save": "saved", "reject": "declined"}[action]
    changed = await database.transition_application_status(
        tenant["id"], app_id, new_status, {"pending", "saved"}
    )
    if not changed:
        raise web.HTTPConflict(text="Bu nomzod bo'yicha boshqa joydan qaror qabul qilindi.")
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


async def candidate_outcome(request: web.Request):
    """Suhbatdan keyingi yakuniy natijani saqlaydi.

    Faqat suhbatga qabul qilingan nomzod yakunlanishi mumkin. Shu tekshiruv
    tasodifiy yoki qayta yuborilgan so'rovlar pipeline tarixini buzmasligini
    ta'minlaydi.
    """
    tenant, _ = await _authorize(request)
    try:
        app_id = int(request.match_info["app_id"])
        body = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise web.HTTPBadRequest(text="Noto'g'ri so'rov.")
    outcome = body.get("outcome")
    if outcome not in {"hired", "not_hired", "no_show"}:
        raise web.HTTPBadRequest(text="Noto'g'ri yakuniy natija.")
    app = await database.get_application(tenant["id"], app_id)
    if not app:
        raise web.HTTPNotFound(text="Nomzod topilmadi.")
    if app["status"] != "accepted":
        raise web.HTTPConflict(text="Faqat suhbatdagi nomzodni yakunlash mumkin.")
    if outcome == "no_show" and not app.get("selected_slot"):
        raise web.HTTPConflict(text="Suhbat vaqti tanlanmagan nomzodni 'kelmadi' deb belgilab bo'lmaydi.")
    changed = await database.transition_application_status(
        tenant["id"], app_id, outcome, {"accepted"}
    )
    if not changed:
        raise web.HTTPConflict(text="Nomzod holati boshqa joydan o'zgartirilgan.")
    await notify_candidate_outcome(tenant["id"], app_id, outcome)
    return web.json_response({"ok": True, "status": outcome})


async def analytics_funnel(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        days = max(1, min(90, int(request.query.get("days", "30"))))
    except ValueError:
        raise web.HTTPBadRequest(text="Davr noto'g'ri.")
    vacancy_key = (request.query.get("vacancy_key") or "").strip() or None
    apps = await database.list_funnel_applications(
        tenant["id"], days=days, vacancy_key=vacancy_key
    )
    return web.json_response({"period_days": days, "funnel": hiring_funnel(apps)})


async def compare_top_candidates(request: web.Request):
    tenant, _ = await _authorize(request)
    vacancy_key = (request.query.get("vacancy_key") or "").strip()
    if not vacancy_key:
        raise web.HTTPBadRequest(text="Vakansiyani tanlang.")
    vacancy = await database.get_vacancy(tenant["id"], vacancy_key)
    if not vacancy:
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    try:
        limit = max(2, min(5, int(request.query.get("limit", "3"))))
    except ValueError:
        limit = 3
    apps = await database.get_applications_for_vacancy(tenant["id"], vacancy_key, limit=500)
    return web.json_response(
        {
            "vacancy": {"key": vacancy["key"], "title": vacancy["title"]},
            "comparison": compare_candidates(apps, vacancy, limit=limit),
        }
    )


async def onboarding_status(request: web.Request):
    tenant, _ = await _authorize(request)
    stats = await database.get_overall_stats(tenant["id"])
    return web.json_response(
        {
            "completed": bool(tenant.get("onboarding_completed_at")),
            "can_quick_setup": stats["total"] == 0,
            "industry": tenant.get("industry"),
            "profile": tenant.get("onboarding_profile") or {},
        }
    )


def _normalise_starts_at(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise web.HTTPBadRequest(text="Suhbat vaqti noto'g'ri formatda.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


async def quick_setup(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        raise web.HTTPBadRequest(text="Onboarding ma'lumoti noto'g'ri.")
    industry = str(body.get("industry") or "").strip()
    role = str(body.get("role_title") or "").strip()
    ideal = str(body.get("ideal_candidate") or "").strip()
    try:
        question_count = int(body.get("question_count", 9))
        salary_budget = body.get("salary_budget_max")
        salary_budget = int(salary_budget) if salary_budget not in (None, "", 0) else None
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(text="Savol yoki maosh qiymati noto'g'ri.")
    if not 2 <= len(industry) <= 100 or not 2 <= len(role) <= 100:
        raise web.HTTPBadRequest(text="Biznes sohasi va lavozimni to'liq yozing.")
    if not 5 <= len(ideal) <= 700:
        raise web.HTTPBadRequest(text="Ideal xodim tavsifini aniqroq yozing.")
    if not 5 <= question_count <= 12:
        raise web.HTTPBadRequest(text="Savollar soni 5 dan 12 gacha bo'lishi kerak.")
    if salary_budget is not None and not 100_000 <= salary_budget <= 1_000_000_000:
        raise web.HTTPBadRequest(text="Maosh budjeti noto'g'ri.")

    raw_slots = body.get("interview_slots") or []
    if not isinstance(raw_slots, list) or len(raw_slots) > 10:
        raise web.HTTPBadRequest(text="Suhbat vaqtlari noto'g'ri.")
    clean_slots = []
    for raw in raw_slots:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()[:80]
        starts_at = _normalise_starts_at(raw.get("starts_at"))
        try:
            capacity = max(1, min(20, int(raw.get("capacity", 1))))
        except (TypeError, ValueError):
            capacity = 1
        if label and starts_at:
            clean_slots.append({"label": label, "starts_at": starts_at, "capacity": capacity})

    description = (
        f"Biznes sohasi: {industry}. Ideal xodim: {ideal}. "
        + (f"Oylik budjeti {salary_budget:,} so'mgacha. " if salary_budget else "")
        + "Savollar real amaliy tajriba, natijadorlik, barqarorlik va mas'uliyatni ajratsin."
    )
    questions = await generate_questions(role, description, count=question_count)
    if not questions:
        raise web.HTTPServiceUnavailable(
            text="AI savollarni tayyorlay olmadi. Birozdan keyin qayta urinib ko'ring."
        )

    stats = await database.get_overall_stats(tenant["id"])
    if stats["total"] == 0:
        await database.deactivate_empty_vacancies(tenant["id"])
        await database.clear_unbooked_interview_slots(tenant["id"])
    else:
        usage = await database.get_subscription_usage(tenant["id"])
        if not usage["vacancies_available"]:
            raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.")

    key = database.make_vacancy_key(role)
    base = key
    suffix = 2
    while await database.get_vacancy(tenant["id"], key):
        key = f"{base[:36]}_{suffix}"
        suffix += 1
    profile = {
        "industry": industry,
        "ideal_candidate": ideal,
        "salary_budget_max": salary_budget,
        "question_count": question_count,
    }
    try:
        await database.create_vacancy(
            tenant_id=tenant["id"],
            key=key,
            title=role,
            reject_message=(
                "Arizangiz uchun rahmat. Hozircha ushbu vakansiya bo'yicha keyingi bosqichga "
                "o'tmadingiz. Sizga muvaffaqiyat tilaymiz!"
            ),
            questions=questions,
            resume_required=False,
            profile=profile,
        )
    except database.VacancyLimitReached as exc:
        raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.") from exc
    for slot in clean_slots:
        await database.add_interview_slot(
            tenant["id"], slot["label"], slot["capacity"], starts_at=slot["starts_at"]
        )
    location = str(body.get("location_text") or "").strip()[:240]
    if location:
        await database.update_interview_settings(tenant["id"], location_text=location)
    await database.update_tenant_onboarding(
        tenant["id"], industry=industry, profile={**profile, "primary_vacancy_key": key}
    )
    return web.json_response({"ok": True, "vacancy_key": key, "questions": len(questions)})


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


def _clean_questions(raw_questions) -> list[dict]:
    if not isinstance(raw_questions, list):
        raise web.HTTPBadRequest(text="Savollar ro'yxati noto'g'ri.")
    result = []
    for index, raw in enumerate(raw_questions, 1):
        text = str(raw.get("text") if isinstance(raw, dict) else raw).strip()
        if not 3 <= len(text) <= 500:
            raise web.HTTPBadRequest(text=f"{index}-savol noto'g'ri yoki juda uzun.")
        result.append(
            {
                "key": f"q{index}",
                "text": text,
                "type": "score",
                "required": True,
            }
        )
    if not 3 <= len(result) <= 20:
        raise web.HTTPBadRequest(text="3 tadan 20 tagacha savol kiriting.")
    return result


async def vacancy_detail(request: web.Request):
    tenant, _ = await _authorize(request)
    vacancy = await database.get_vacancy(tenant["id"], request.match_info["vacancy_key"])
    if not vacancy:
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    return web.json_response(
        {
            "key": vacancy["key"],
            "title": vacancy["title"],
            "questions": vacancy["questions"],
            "reject_message": vacancy["reject_message"],
            "resume_required": vacancy["resume_required"],
            "active": vacancy["active"],
        }
    )


async def create_vacancy(request: web.Request):
    tenant, _ = await _authorize(request)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="Vakansiya ma'lumoti noto'g'ri.")
    title = str(body.get("title") or "").strip()
    reject_message = str(body.get("reject_message") or "").strip()
    if not 2 <= len(title) <= 100:
        raise web.HTTPBadRequest(text="Lavozim nomini to'liq yozing.")
    if not 5 <= len(reject_message) <= 500:
        raise web.HTTPBadRequest(text="Rad javobini 5–500 belgi oralig'ida yozing.")
    questions = _clean_questions(body.get("questions"))
    usage = await database.get_subscription_usage(tenant["id"])
    if not usage["vacancies_available"]:
        raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.")
    base_key = database.make_vacancy_key(title)
    key = base_key
    suffix = 2
    while await database.get_vacancy(tenant["id"], key):
        key = f"{base_key[:36]}_{suffix}"
        suffix += 1
    try:
        await database.create_vacancy(
            tenant_id=tenant["id"],
            key=key,
            title=title,
            reject_message=reject_message,
            questions=questions,
            resume_required=bool(body.get("resume_required")),
        )
    except database.VacancyLimitReached as exc:
        raise web.HTTPPaymentRequired(text="Tarifdagi vakansiya limiti tugagan.") from exc
    return web.json_response({"ok": True, "key": key}, status=201)


async def edit_vacancy(request: web.Request):
    tenant, _ = await _authorize(request)
    key = request.match_info["vacancy_key"]
    if not await database.get_vacancy(tenant["id"], key):
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise web.HTTPBadRequest(text="Vakansiya ma'lumoti noto'g'ri.")
    title = str(body.get("title") or "").strip()
    reject_message = str(body.get("reject_message") or "").strip()
    if not 2 <= len(title) <= 100 or not 5 <= len(reject_message) <= 500:
        raise web.HTTPBadRequest(text="Vakansiya maydonlarini to'liq kiriting.")
    await database.update_vacancy(
        tenant["id"],
        key,
        title=title,
        reject_message=reject_message,
        questions=_clean_questions(body.get("questions")),
        resume_required=bool(body.get("resume_required")),
    )
    return web.json_response({"ok": True, "key": key})


async def export_vacancy(request: web.Request):
    tenant, _ = await _authorize(request)
    key = request.match_info["vacancy_key"]
    vacancy = await database.get_vacancy(tenant["id"], key)
    if not vacancy:
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    apps = await database.get_applications_for_vacancy(tenant["id"], key)
    wb = Workbook()
    ws = wb.active
    ws.title = "Nomzodlar"
    headers = ["#", "Ism-familiya", "Username", "Telefon", "Holat", "Ariza sanasi", "Suhbat vaqti", "Javoblar"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    labels = {"pending":"Kutilmoqda","saved":"Keyin ko'rish","accepted":"Suhbatda","declined":"Rad etildi","hired":"Ishga olindi","not_hired":"Ishga olinmadi","no_show":"Suhbatga kelmadi"}
    for index, item in enumerate(apps, 1):
        ws.append([index, item["full_name"], item.get("username") or "", item.get("phone_number") or "", labels.get(item["status"], item["status"]), (item.get("created_at") or "")[:16].replace("T", " "), item.get("selected_slot") or "", " | ".join(str(value) for value in (item.get("answers") or {}).values())])
    for index, width in enumerate([4, 24, 18, 18, 20, 18, 22, 80], 1):
        ws.column_dimensions[chr(64 + index)].width = width
    output = io.BytesIO()
    wb.save(output)
    safe_title = "".join(char if char.isalnum() else "_" for char in vacancy["title"])[:40]
    return web.Response(
        body=output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}_nomzodlar.xlsx"'},
    )


async def toggle_vacancy(request: web.Request):
    tenant, _ = await _authorize(request)
    key = request.match_info["vacancy_key"]
    vacancy = await database.get_vacancy(tenant["id"], key)
    if not vacancy:
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    target = not vacancy["active"]
    try:
        changed = await database.set_vacancy_active(tenant["id"], key, target)
    except database.VacancyLimitReached as exc:
        raise web.HTTPPaymentRequired(
            text="Tarifdagi faol vakansiya limiti tugagan. Boshqa vakansiyani yoping yoki tarifni oshiring."
        ) from exc
    if not changed:
        raise web.HTTPNotFound(text="Vakansiya topilmadi.")
    return web.json_response({"ok": True, "active": target})


async def billing(request: web.Request):
    tenant, _ = await _authorize(request)
    usage = await database.get_subscription_usage(tenant["id"])
    return web.json_response(
        {
            "current": {
                "code": usage["plan"].code,
                "name": usage["plan"].name,
                "expires_at": usage["expires_at"],
                "expired": usage["expired"],
            },
            "plans": [
                {
                    "code": code,
                    "name": get_plan(code).name,
                    "price": get_plan(code).price,
                    "applications": get_plan(code).application_limit,
                    "vacancies": get_plan(code).vacancy_limit,
                    "purchase_state": get_plan_transition(
                        usage["plan"].code,
                        code,
                        current_expired=usage["expired"],
                    ),
                }
                for code in PUBLIC_PLAN_CODES
            ],
        }
    )


async def create_billing_order(request: web.Request):
    tenant, _ = await _authorize(request)
    if not PAYMENT_CARD_NUMBER:
        raise web.HTTPServiceUnavailable(text="To'lov rekvizitlari hali sozlanmagan.")
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        raise web.HTTPBadRequest(text="Tarif ma'lumoti noto'g'ri.")
    plan_code = str(body.get("plan_code") or "").strip().lower()
    if plan_code not in PUBLIC_PLAN_CODES:
        raise web.HTTPBadRequest(text="Tarif topilmadi.")
    usage = await database.get_subscription_usage(tenant["id"])
    transition = get_plan_transition(
        usage["plan"].code,
        plan_code,
        current_expired=usage["expired"],
    )
    if transition == "blocked":
        expiry = (usage.get("expires_at") or "")[:10]
        suffix = f" ({expiry} gacha)" if expiry else ""
        raise web.HTTPConflict(
            text=(
                f"{usage['plan'].name} tarifi{suffix} faol. "
                "Past tarifni joriy muddat tugagach tanlashingiz mumkin."
            )
        )
    plan = get_plan(plan_code)
    order = await create_payment_order_for_plan(
        tenant["id"], plan.price, plan_code=plan_code
    )
    return web.json_response(
        {
            "ok": True,
            "order_code": order["order_code"],
            "amount": order["amount"],
            "expires_at": order["expires_at"],
            "status": "awaiting_payment",
            "plan": {"code": plan.code, "name": plan.name},
            "card_number": PAYMENT_CARD_NUMBER,
            "card_holder": PAYMENT_CARD_HOLDER,
        },
        status=201,
    )


async def billing_order_status(request: web.Request):
    tenant, _ = await _authorize(request)
    order_code = str(request.match_info.get("order_code") or "").strip()
    if not order_code or len(order_code) > 40:
        raise web.HTTPNotFound()
    order = await database.get_payment_order_for_tenant(tenant["id"], order_code)
    if not order:
        raise web.HTTPNotFound(text="To'lov buyurtmasi topilmadi.")
    return web.json_response(
        {
            "order_code": order["order_code"],
            "status": order["status"],
            "amount": order["amount"],
            "plan_code": order.get("plan_code", "start"),
            "expires_at": order["expires_at"],
        }
    )


def register_miniapp(app: web.Application) -> None:
    app.middlewares.append(security_headers)
    app.router.add_get("/health", health)
    app.router.add_get("/miniapp/{tenant_id}", index)
    app.router.add_static(
        "/miniapp-assets", STATIC_DIR, show_index=False, append_version=True
    )
    app.router.add_get("/api/miniapp/{tenant_id}/dashboard", dashboard)
    app.router.add_get("/api/miniapp/{tenant_id}/analytics/funnel", analytics_funnel)
    app.router.add_get(
        "/api/miniapp/{tenant_id}/intelligence/compare", compare_top_candidates
    )
    app.router.add_get("/api/miniapp/{tenant_id}/onboarding/status", onboarding_status)
    app.router.add_post(
        "/api/miniapp/{tenant_id}/onboarding/quick-setup", quick_setup
    )
    app.router.add_get("/api/miniapp/{tenant_id}/candidates", candidates)
    app.router.add_get("/api/miniapp/{tenant_id}/candidates/{app_id}", candidate_detail)
    app.router.add_post(
        "/api/miniapp/{tenant_id}/candidates/{app_id}/decision", candidate_decision
    )
    app.router.add_post(
        "/api/miniapp/{tenant_id}/candidates/{app_id}/outcome", candidate_outcome
    )
    app.router.add_get("/api/miniapp/{tenant_id}/vacancies", vacancies)
    app.router.add_post("/api/miniapp/{tenant_id}/vacancies", create_vacancy)
    app.router.add_get(
        "/api/miniapp/{tenant_id}/vacancies/{vacancy_key}", vacancy_detail
    )
    app.router.add_put(
        "/api/miniapp/{tenant_id}/vacancies/{vacancy_key}", edit_vacancy
    )
    app.router.add_get(
        "/api/miniapp/{tenant_id}/vacancies/{vacancy_key}/export", export_vacancy
    )
    app.router.add_post(
        "/api/miniapp/{tenant_id}/vacancies/{vacancy_key}/toggle", toggle_vacancy
    )
    app.router.add_get("/api/miniapp/{tenant_id}/billing", billing)
    app.router.add_post("/api/miniapp/{tenant_id}/billing/orders", create_billing_order)
    app.router.add_get(
        "/api/miniapp/{tenant_id}/billing/orders/{order_code}", billing_order_status
    )
    app.router.add_get("/api/miniapp/{tenant_id}/interviews", interviews)
    app.router.add_post("/api/miniapp/{tenant_id}/interviews/slots", add_interview_slot)
    app.router.add_delete(
        "/api/miniapp/{tenant_id}/interviews/slots/{slot_id}", delete_interview_slot
    )
    app.router.add_post(
        "/api/miniapp/{tenant_id}/interviews/settings", update_interview_settings
    )
    app.router.add_post(
        "/api/miniapp/{tenant_id}/interviews/{app_id}/remind", remind_interview_candidate
    )
