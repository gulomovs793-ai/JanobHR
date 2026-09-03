"""Lead va obuna eslatmalari. Har bir xabar idempotent kalit bilan himoyalangan."""

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS
from services import database

logger = logging.getLogger("janob_hr_reminders")


async def _send_founder_lead_reminders() -> None:
    if not FOUNDER_BOT_TOKEN or not FOUNDER_USER_IDS:
        return
    leads = await database.list_leads_older_than(minutes=30)
    if not leads:
        return
    bot = Bot(token=FOUNDER_BOT_TOKEN)
    try:
        for lead in leads:
            age_hours = max(
                0,
                int(
                    (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(lead["created_at"])
                    ).total_seconds()
                    // 3600
                ),
            )
            stage = "24h" if age_hours >= 24 else "30m"
            day = (
                datetime.now(timezone.utc).date().isoformat()
                if stage == "24h"
                else "once"
            )
            key = f"lead:{lead['id']}:{stage}:{day}"
            if await database.was_system_notification_sent(key):
                continue
            text = (
                "⏰ <b>Lid javobsiz qolgan</b>\n\n"
                f"Kompaniya: <b>{lead.get('company_name') or '—'}</b>\n"
                f"Kontakt: {lead.get('contact_name') or '—'}\n"
                f"Telefon: <code>{lead['contact_phone']}</code>\n"
                f"Holat: {lead['status']}\n\n"
                "Bog'laning yoki founder botdagi 📞 Lidlar bo'limidan holatini yangilang."
            )
            sent = False
            for founder_id in FOUNDER_USER_IDS:
                try:
                    await bot.send_message(
                        founder_id,
                        text,
                        parse_mode=ParseMode.HTML,
                    )
                    sent = True
                except Exception:
                    logger.exception(
                        "Lid eslatmasi founderga yuborilmadi: %s", founder_id
                    )
            if sent:
                await database.mark_system_notification_sent(key)
    finally:
        await bot.session.close()


async def _send_subscription_reminders() -> None:
    for tenant in await database.list_subscription_reminder_candidates():
        if not tenant.get("admin_bot_token") or not tenant.get("admin_user_ids"):
            continue
        expiry = datetime.fromisoformat(tenant["subscription_expires_at"])
        now = datetime.now(timezone.utc)
        calendar_days = (expiry.date() - now.date()).days
        if calendar_days not in {5, 2, 0} and expiry >= now:
            continue
        stage = str(calendar_days) if expiry >= now else "expired"
        key = f"subscription:{tenant['id']}:{expiry.date()}:{stage}"
        if await database.was_system_notification_sent(key):
            continue
        bot = Bot(token=tenant["admin_bot_token"])
        sent = False
        try:
            for admin_id in tenant["admin_user_ids"]:
                try:
                    builder = InlineKeyboardBuilder()
                    builder.button(
                        text="💳 Tarifni yangilash", callback_data="menu:billing"
                    )
                    if expiry < now:
                        title = "⛔ Tarif muddati tugadi"
                        body = (
                            "Botlar ishlashini davom ettirish uchun tarifni yangilang."
                        )
                    elif calendar_days == 0:
                        title = "⏰ Tarif bugun tugaydi"
                        body = "Uzilish bo'lmasligi uchun tarifni bugun yangilang."
                    else:
                        title = f"⏰ Tarif tugashiga {calendar_days} kun qoldi"
                        body = "Botlar to'xtab qolmasligi uchun tarifni yangilang."
                    await bot.send_message(
                        admin_id,
                        f"<b>{title}</b>\n\n{body}",
                        reply_markup=builder.as_markup(),
                        parse_mode=ParseMode.HTML,
                    )
                    sent = True
                except Exception:
                    logger.exception(
                        "Obuna eslatmasi yuborilmadi: tenant=%s", tenant["id"]
                    )
        finally:
            await bot.session.close()
        if sent:
            await database.mark_system_notification_sent(key)


async def _send_unpaid_order_reminders() -> None:
    if not FOUNDER_BOT_TOKEN or not FOUNDER_USER_IDS:
        return
    orders = await database.list_unpaid_orders_older_than(minutes=30)
    bot = Bot(token=FOUNDER_BOT_TOKEN)
    try:
        for order in orders:
            age_hours = int(
                (
                    datetime.now(timezone.utc)
                    - datetime.fromisoformat(order["created_at"])
                ).total_seconds()
                // 3600
            )
            stage = "24h" if age_hours >= 24 else "30m"
            day = (
                datetime.now(timezone.utc).date().isoformat()
                if stage == "24h"
                else "once"
            )
            key = f"payment:{order['id']}:{stage}:{day}"
            if await database.was_system_notification_sent(key):
                continue
            sent = False
            for founder_id in FOUNDER_USER_IDS:
                try:
                    await bot.send_message(
                        founder_id,
                        "💳 <b>To'lov hali kelmadi</b>\n\n"
                        f"Kompaniya: <b>{order['company_name']}</b>\n"
                        f"Buyurtma: <code>{order['order_code']}</code>\n"
                        f"Summa: <b>{order['amount']:,} so'm</b>\n"
                        f"Telefon: <code>{order.get('contact_phone') or '—'}</code>",
                        parse_mode=ParseMode.HTML,
                    )
                    sent = True
                except Exception:
                    logger.exception("To'lov eslatmasi founderga yuborilmadi")
            if sent:
                await database.mark_system_notification_sent(key)
    finally:
        await bot.session.close()


async def run_reminders_forever() -> None:
    while True:
        try:
            await _send_founder_lead_reminders()
            await _send_subscription_reminders()
            await _send_unpaid_order_reminders()
        except Exception:
            logger.exception("Eslatmalar siklida xato")
        await asyncio.sleep(600)
