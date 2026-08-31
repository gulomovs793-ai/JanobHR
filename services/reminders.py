"""Lead va obuna eslatmalari. Har bir xabar idempotent kalit bilan himoyalangan."""

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS
from services import database

logger = logging.getLogger("janob_hr_reminders")


async def _send_founder_lead_reminders() -> None:
    if not FOUNDER_BOT_TOKEN or not FOUNDER_USER_IDS:
        return
    leads = await database.list_due_lead_reminders(hours=24)
    if not leads:
        return
    bot = Bot(token=FOUNDER_BOT_TOKEN)
    try:
        for lead in leads:
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
                    await bot.send_message(founder_id, text)
                    sent = True
                except Exception:
                    logger.exception(
                        "Lid eslatmasi founderga yuborilmadi: %s", founder_id
                    )
            if sent:
                await database.mark_lead_reminded(lead["id"])
    finally:
        await bot.session.close()


async def _send_subscription_reminders() -> None:
    for days in (5, 2, 1):
        for tenant in await database.list_expiring_subscriptions(days):
            if not tenant.get("admin_bot_token") or not tenant.get("admin_user_ids"):
                continue
            expiry = datetime.fromisoformat(tenant["subscription_expires_at"])
            remaining = max(0, (expiry - datetime.now(timezone.utc)).days + 1)
            if remaining != days:
                continue
            key = f"subscription:{tenant['id']}:{expiry.date()}:{days}"
            if await database.was_system_notification_sent(key):
                continue
            bot = Bot(token=tenant["admin_bot_token"])
            sent = False
            try:
                for admin_id in tenant["admin_user_ids"]:
                    try:
                        await bot.send_message(
                            admin_id,
                            f"⏰ <b>Tarif tugashiga {days} kun qoldi</b>\n\n"
                            "Botlar to'xtab qolmasligi uchun 💳 Tarif va limitlar bo'limidan uzaytiring.",
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


async def run_reminders_forever() -> None:
    while True:
        try:
            await _send_founder_lead_reminders()
            await _send_subscription_reminders()
        except Exception:
            logger.exception("Eslatmalar siklida xato")
        await asyncio.sleep(3600)
