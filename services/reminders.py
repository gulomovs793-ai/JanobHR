"""Lead va obuna eslatmalari. Har bir xabar idempotent kalit bilan himoyalangan."""

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS
from services import database
from services.storage import (
    list_stale_candidate_sessions,
    mark_candidate_session_reminded,
)

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


async def _send_abandoned_application_reminders() -> None:
    for session in await list_stale_candidate_sessions(minutes=30):
        tenant = await database.get_tenant(session["tenant_id"])
        if not tenant or tenant.get("status") != "active":
            continue
        lang = (session.get("data") or {}).get("lang", "uz")
        if session["stage"] == "24h":
            text = (
                "Ваша анкета ещё не завершена. Можете продолжить с того же места или отправить /cancel."
                if lang == "ru"
                else "Arizangiz hali yakunlanmagan. Shu yerdan davom ettirishingiz yoki /cancel bilan bekor qilishingiz mumkin."
            )
        else:
            text = (
                "Вы остановились на середине анкеты. Продолжите с последнего вопроса — ответы уже сохранены."
                if lang == "ru"
                else "Arizangiz yarim qolib ketdi. Oxirgi savoldan davom eting — oldingi javoblaringiz saqlangan."
            )
        bot = Bot(token=tenant["bot_token"])
        try:
            await bot.send_message(session["chat_id"], text)
            await mark_candidate_session_reminded(session["storage_key"], session["stage"])
        except Exception:
            logger.exception("Yarim qolgan ariza eslatmasi yuborilmadi: tenant=%s", tenant["id"])
        finally:
            await bot.session.close()


async def _send_interview_automatic_followups() -> None:
    now = datetime.now(timezone.utc)
    for item in await database.list_interview_followup_candidates():
        try:
            starts_at = datetime.fromisoformat(item["starts_at"])
            if starts_at.tzinfo is None:
                starts_at = starts_at.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        minutes = (starts_at - now).total_seconds() / 60
        if minutes > 0:
            if minutes <= 120:
                stage = "2h"
                text = f"⏰ Suhbatga taxminan 2 soat qoldi. Vaqt: {item['selected_slot']}"
            elif minutes <= 1440:
                stage = "24h"
                text = f"📅 Eslatma: ertaga suhbat bor. Vaqt: {item['selected_slot']}"
            else:
                continue
            key = f"interview:{item['app_id']}:{stage}"
            if await database.was_system_notification_sent(key):
                continue
            bot = Bot(token=item["bot_token"])
            try:
                await bot.send_message(item["user_id"], text)
                await database.mark_system_notification_sent(key)
            except Exception:
                logger.exception("Suhbat eslatmasi yuborilmadi: app=%s", item["app_id"])
            finally:
                await bot.session.close()
            continue

        # Suhbat o'tganidan keyin adminni natijani belgilashga chaqiramiz.
        if minutes < -1440 or not item.get("admin_bot_token"):
            continue
        key = f"interview:{item['app_id']}:outcome_prompt"
        if await database.was_system_notification_sent(key):
            continue
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ Ishga olindi", callback_data=f"ivoutcome:{item['app_id']}:hired")
        builder.button(text="❌ Ishga olinmadi", callback_data=f"ivoutcome:{item['app_id']}:not_hired")
        builder.button(text="🚫 Kelmadi", callback_data=f"ivoutcome:{item['app_id']}:no_show")
        builder.adjust(1)
        bot = Bot(token=item["admin_bot_token"])
        sent = False
        try:
            for admin_id in item.get("admin_user_ids") or []:
                await bot.send_message(
                    admin_id,
                    f"📋 <b>Suhbat natijasini belgilang</b>\n\n"
                    f"Nomzod: <b>{item['full_name']}</b>\n"
                    f"Lavozim: {item['vacancy_title']}\nVaqt: {item['selected_slot']}",
                    reply_markup=builder.as_markup(),
                    parse_mode=ParseMode.HTML,
                )
                sent = True
        except Exception:
            logger.exception("Suhbat natijasi prompti yuborilmadi: app=%s", item["app_id"])
        finally:
            await bot.session.close()
        if sent:
            await database.mark_system_notification_sent(key)


async def run_reminders_forever() -> None:
    while True:
        try:
            await _send_founder_lead_reminders()
            await _send_subscription_reminders()
            await _send_unpaid_order_reminders()
            await _send_abandoned_application_reminders()
            await _send_interview_automatic_followups()
        except Exception:
            logger.exception("Eslatmalar siklida xato")
        await asyncio.sleep(300)
