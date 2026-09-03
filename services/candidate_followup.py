"""Nomzod va admin follow-up xabarlari uchun yagona qatlam."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from services import database

logger = logging.getLogger("janob_hr_followup")


async def notify_candidate_outcome(tenant_id: int, app_id: int, outcome: str) -> None:
    """Yakuniy natijadan keyin nomzodga kerakli xabarni yuboradi.

    Hozir faqat hired holatida onboarding xabari yuboriladi. Bu admin xatosi
    bilan rad javobini qayta-qayta yuborib yubormaslik uchun ataylab konservativ.
    """
    if outcome != "hired":
        return
    tenant = await database.get_tenant(tenant_id)
    app = await database.get_application(tenant_id, app_id)
    if not tenant or not app:
        return
    settings = await database.get_interview_settings(tenant_id)
    lines = [
        "🎉 <b>Tabriklaymiz! Siz ishga qabul qilindingiz.</b>",
        "",
        f"💼 Lavozim: <b>{escape(str(app['vacancy_title']))}</b>",
        "Kompaniya vakili keyingi qadamlar va ish boshlash sanasi bo'yicha siz bilan bog'lanadi.",
    ]
    if settings.get("interviewer_name"):
        lines += ["", f"Mas'ul: {escape(str(settings['interviewer_name']))}"]
    if settings.get("interviewer_phone"):
        lines.append(f"Telefon: <code>{escape(str(settings['interviewer_phone']))}</code>")
    bot = Bot(
        token=tenant["bot_token"],
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await bot.send_message(app["user_id"], "\n".join(lines))
    except Exception:
        logger.exception("Ishga olingan nomzodga onboarding xabari yuborilmadi: app=%s", app_id)
    finally:
        await bot.session.close()
