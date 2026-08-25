"""Qabul qilingan nomzod 30/90 kundan keyin ishda qanday natija ko'rsatayotgani
haqida ish beruvchidan so'raydigan fon vazifasi (retention feedback loop).

MAQSAD: suhbatda yaxshi javob berish bilan ishda yaxshi ishlash — ikki xil
narsa. Bu ma'lumot yig'ilib borgach, "qaysi javob turi haqiqatan yaxshi
xodimni bashorat qiladi" degan haqiqiy tahlil qilish imkoniyati paydo bo'ladi.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database

logger = logging.getLogger("janob_hr_bot")

_CHECK_INTERVAL_SECONDS = 6 * 3600  # har 6 soatda tekshiradi
_CHECKPOINTS = [30, 90]


async def run_outcome_followups():
    """bot.py'dagi asosiy tasklar ro'yxatiga qo'shiladigan cheksiz fon sikli."""
    while True:
        try:
            await _check_due_followups()
        except Exception:
            logger.exception("Natija so'rovi tekshiruvida xato.")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)


async def _check_due_followups():
    due = await database.get_applications_due_for_followup(_CHECKPOINTS)
    for app in due:
        await _send_followup(app)


async def _send_followup(app: dict):
    tenant = await database.get_tenant(app["tenant_id"])
    if not tenant or not tenant.get("admin_bot_token") or not tenant["admin_user_ids"]:
        return

    days = app["_due_days"]
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Hali ishlayapti, yaxshi", callback_data=f"outcome:{app['id']}:{days}:good")
    builder.button(text="🟡 Hali ishlayapti, o'rtacha", callback_data=f"outcome:{app['id']}:{days}:ok")
    builder.button(text="❌ Ishlamayapti/ketgan", callback_data=f"outcome:{app['id']}:{days}:left")
    builder.adjust(1)

    admin_bot = Bot(token=tenant["admin_bot_token"])
    try:
        for admin_id in tenant["admin_user_ids"]:
            try:
                await admin_bot.send_message(
                    chat_id=admin_id,
                    text=(
                        f"📋 <b>{days} kun oldin</b> qabul qilingan <b>{app['full_name']}</b> "
                        f"({app['vacancy_title']}) hali ishlayaptimi, natijasi qandoq?"
                    ),
                    reply_markup=builder.as_markup(),
                )
            except Exception:
                logger.exception("Natija so'rovini yuborib bo'lmadi (admin_id=%s).", admin_id)
    finally:
        await admin_bot.session.close()

    await database.mark_followup_sent(app["id"], days)
