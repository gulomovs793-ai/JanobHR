"""
Janob HR — @CardXabarBot (yoki shunga o'xshash) xabarlarini TO'G'RIDAN-TO'G'RI
o'qiydigan userbot.

QANDAY ISHLAYDI: server Telegram'ga SIZNING shaxsiy hisobingiz nomidan
ulanadi (MTProto orqali, Telethon kutubxonasi) va FAQAT `CARD_BOT_USERNAME`
sozlamasida ko'rsatilgan botdan kelgan xabarlarni tinglaydi. Xabar kelishi
bilan `services.payment_automation.handle_payment_notification`ga uzatadi.

⚠️ OGOHLANTIRISH: bu shaxsiy hisobni avtomatlashtirish. Sessiya kaliti
(`TELEGRAM_USERBOT_SESSION`) hisobingizga TO'LIQ kirish huquqini beradi —
uni faqat muhit o'zgaruvchisida saqlang, hech qachon kodga yozmang.

Ishga tushirish: `python userbot.py` (Render'da alohida Background Worker
sifatida, FOUNDER_BOT_TOKEN bilan bir xil xizmatda ham ishga tushirish mumkin).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import (
    CARD_BOT_USERNAME,
    FOUNDER_USER_IDS,
    ORDER_TTL_MINUTES,
    OVOZ_PAYMENT_URL,
    PAYMENT_ROUTER_SECRET,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_USERBOT_SESSION,
)
from services import database
from services.payment_automation import (
    handle_payment_notification,
    parse_notification_amount,
)
from services.plans import format_som, get_plan
from services.tenant_activation import activate_tenant

logger = logging.getLogger("janob_hr_userbot")


_OVOZ_LAST_DIGITS = {1, 2, 3, 4}
_JANOBHR_LAST_DIGITS = {6, 7, 8, 9}


async def _forward_to_ovoz(raw_text: str, amount: int | None) -> dict:
    """Forward one signed bank notification to the O'zbek Ovoz payment engine.

    The Ovoz service may be on Render Free and asleep. The long timeout plus
    retry lets the incoming HTTP request wake it without losing the payment.
    """
    if not OVOZ_PAYMENT_URL or not PAYMENT_ROUTER_SECRET:
        logger.error("[payment-router] OVOZ_PAYMENT_URL/PAYMENT_ROUTER_SECRET sozlanmagan.")
        return {"status": "router_not_configured", "amount": amount, "_project": "ovoz"}

    headers = {
        "X-Payment-Router-Secret": PAYMENT_ROUTER_SECRET,
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=95, connect=15)
    retryable = {429, 502, 503, 504}
    last_status = None
    for attempt in range(1, 4):
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.post(
                    OVOZ_PAYMENT_URL,
                    headers=headers,
                    json={"raw_text": raw_text, "source": "janobhr-web"},
                ) as response,
            ):
                last_status = response.status
                body = await response.json(content_type=None)
                if 200 <= response.status < 300:
                    result = body if isinstance(body, dict) else {"status": "ok"}
                    result["_project"] = "ovoz"
                    logger.info(
                        "[payment-router] Ovoz natija: %s, summa=%s",
                        result.get("status"), amount,
                    )
                    return result
                if response.status not in retryable:
                    logger.error(
                        "[payment-router] Ovoz HTTP %s: %s", response.status, str(body)[:300]
                    )
                    return {
                        "status": "router_error",
                        "http_status": response.status,
                        "amount": amount,
                        "_project": "ovoz",
                    }
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.warning(
                "[payment-router] Ovoz urinish %s/3 muvaffaqiyatsiz: %s", attempt, exc
            )
        if attempt < 3:
            await asyncio.sleep(8 * attempt)

    return {
        "status": "router_error",
        "http_status": last_status,
        "amount": amount,
        "_project": "ovoz",
    }


async def _route_payment_notification(raw_text: str) -> dict:
    """One physical card, two isolated payment engines.

    New Ovoz amounts end in 1/2/3/4 and Janob HR in 6/7/8/9. Legacy 0/5
    and old orders are still given a fallback chance in the other engine.
    """
    amount = parse_notification_amount(raw_text)

    async def local(*, notify_no_match: bool = False) -> dict:
        result = await handle_payment_notification(
            raw_text,
            _notify_founders,
            _activate_tenant_wrapper,
            notify_no_match=notify_no_match,
        )
        result["_project"] = "janobhr"
        return result

    if amount is None:
        return await local(notify_no_match=False)

    last_digit = amount % 10
    if last_digit in _OVOZ_LAST_DIGITS:
        routed = await _forward_to_ovoz(raw_text, amount)
        if routed.get("status") not in {"no_match", "router_error", "router_not_configured"}:
            return routed
        # Legacy Janob HR order may predate the namespace split.
        legacy = await local(notify_no_match=False)
        if legacy.get("status") != "no_match":
            return legacy
        return routed

    # Janob HR namespace (and legacy/reserved digits): local engine first.
    result = await local(notify_no_match=False)
    if result.get("status") != "no_match":
        return result

    # A legacy Ovoz order may use an old last digit.
    routed = await _forward_to_ovoz(raw_text, amount)
    if routed.get("status") in {"router_error", "router_not_configured"}:
        # If neither engine can be checked, surface the unknown incoming payment
        # to founders instead of silently dropping it.
        return await local(notify_no_match=True)
    return routed


def is_userbot_configured() -> bool:
    return bool(TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USERBOT_SESSION)


async def _notify_founders(text: str):
    """Asoschilarga xabar yuborish — FOUNDER_BOT_TOKEN orqali (agar
    sozlangan bo'lsa), aks holda faqat logga yoziladi."""
    from config import FOUNDER_BOT_TOKEN

    if not FOUNDER_BOT_TOKEN or not FOUNDER_USER_IDS:
        logger.warning(
            "[to'lov] Asoschiga xabar yuborilmadi (bot/ID sozlanmagan): %s", text[:200]
        )
        return

    from aiogram import Bot

    bot = Bot(token=FOUNDER_BOT_TOKEN)
    for founder_id in FOUNDER_USER_IDS:
        try:
            await bot.send_message(chat_id=founder_id, text=text)
        except Exception:
            logger.exception("Asoschiga (id=%s) xabar yuborib bo'lmadi.", founder_id)
    await bot.session.close()


async def _activate_tenant_wrapper(tenant_id: int):
    result = await activate_tenant(tenant_id)
    if not result["ok"]:
        raise RuntimeError(result["error"])
    return result


async def _notify_tenant_payment_approved(result: dict) -> None:
    """To'lov tasdiqlanganda mijozga aynan o'z Admin botidan chek yuboradi."""
    from aiogram import Bot

    tenant = await database.get_tenant(result["tenant_id"])
    if not tenant or not tenant.get("admin_bot_token"):
        logger.error("[to'lov] Mijozga tasdiq yuborilmadi: admin bot topilmadi.")
        return
    plan = get_plan(tenant.get("plan_code"))
    expiry = (tenant.get("subscription_expires_at") or "")[:10]
    text = (
        "✅ TO'LOV QABUL QILINDI\n\n"
        f"Tarif: {plan.name}\n"
        f"Summa: {format_som(result['amount'])}\n"
        f"Buyurtma: {result['order_code']}\n"
        f"Amal qilish sanasi: {expiry}\n\n"
        "Tarifingiz faol. Boshqarish uchun /start bosing."
    )
    bot = Bot(token=tenant["admin_bot_token"])
    try:
        for admin_id in tenant["admin_user_ids"]:
            try:
                await bot.send_message(admin_id, text)
            except Exception:
                logger.exception(
                    "[to'lov] Mijoz adminiga tasdiq yuborilmadi (id=%s).", admin_id
                )
    finally:
        await bot.session.close()
    await database.mark_customer_payment_notified(result["order_code"])
    logger.info(
        "[to'lov] Mijozga tasdiq yuborildi: %s",
        result["order_code"],
    )


async def start_userbot():
    if not is_userbot_configured():
        logger.info(
            "[userbot] Sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — o'tkazib yuborildi."
        )
        return

    started_at = datetime.now(timezone.utc)
    client = TelegramClient(
        StringSession(TELEGRAM_USERBOT_SESSION),
        TELEGRAM_API_ID,
        TELEGRAM_API_HASH,
        connection_retries=10,
        retry_delay=3,
        auto_reconnect=True,
    )
    await client.connect()

    me = await client.get_me()
    uname = f"@{me.username}" if getattr(me, "username", None) else "(username yo'q)"
    expected = CARD_BOT_USERNAME.lower()
    logger.info("[userbot] Ulandi: %s. Kuzatilayotgan bot: @%s", uname, expected)
    await database.clear_old_payment_notifications(days=7)
    for approved_order in await database.list_unnotified_approved_orders(hours=24):
        await _notify_tenant_payment_approved(
            {
                "tenant_id": approved_order["tenant_id"],
                "amount": approved_order["amount"],
                "order_code": approved_order["order_code"],
            }
        )

    async def process_message(message):
        try:
            text = (message.message or "").strip()
            if not text:
                return

            # --- ENG MUHIM HIMOYA: faqat aynan shu botdan kelgan xabar qabul qilinadi ---
            sender = await message.get_sender()
            sender_username = (getattr(sender, "username", "") or "").lower()
            if not sender_username or sender_username != expected:
                return
            if not getattr(sender, "bot", False):
                logger.warning(
                    "[userbot] @%s bot emas — e'tiborsiz qoldirildi.", sender_username
                )
                return

            logger.info(
                "[userbot] @%s dan xabar keldi (%d belgi).", expected, len(text)
            )
            result = await _route_payment_notification(text)
            logger.info(
                "[userbot] Natija: %s (%s)",
                result.get("status"),
                result.get("_project", "unknown"),
            )
            if result.get("status") == "approved" and result.get("_project") == "janobhr":
                await _notify_tenant_payment_approved(result)
        except Exception:
            logger.exception("[userbot] Xabarni qayta ishlashda xatolik.")

    @client.on(events.NewMessage())
    async def handler(event):
        await process_message(event.message)

    # Deploy paytida kelgan haqiqiy to'lov yo'qolib ketmasin, ammo eski tarix
    # qayta ishlanib founderga spam bermasin. Ochiq buyurtma ORDER_TTL_MINUTES
    # ichida baribir eskiradi, shuning uchun undan eski xabarni replay qilishning
    # foydasi yo'q.
    replay_cutoff = started_at - timedelta(minutes=max(ORDER_TTL_MINUTES, 1))
    replayed = 0
    try:
        async for old_message in client.iter_messages(CARD_BOT_USERNAME, limit=20):
            message_date = getattr(old_message, "date", None)
            if message_date is None:
                continue
            if message_date.tzinfo is None:
                message_date = message_date.replace(tzinfo=timezone.utc)
            if message_date < replay_cutoff:
                continue
            await process_message(old_message)
            replayed += 1
    except Exception:
        logger.exception("[userbot] Oxirgi to'lov xabarlarini tekshirib bo'lmadi.")

    logger.info(
        "[userbot] Tinglashni boshladi. Replay qilingan yaqindagi xabarlar: %d",
        replayed,
    )
    await client.run_until_disconnected()


async def main():
    await database.init_db()
    await start_userbot()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
