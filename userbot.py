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

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from config import (
    CARD_BOT_USERNAME,
    FOUNDER_USER_IDS,
    TELEGRAM_API_HASH,
    TELEGRAM_API_ID,
    TELEGRAM_USERBOT_SESSION,
)
from services import database
from services.payment_automation import handle_payment_notification
from services.plans import format_som, get_plan
from services.tenant_activation import activate_tenant

logger = logging.getLogger("janob_hr_userbot")


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


async def start_userbot():
    if not is_userbot_configured():
        logger.info(
            "[userbot] Sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — o'tkazib yuborildi."
        )
        return

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
    await database.clear_recent_payment_notifications(minutes=60)

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
            result = await handle_payment_notification(
                text, _notify_founders, _activate_tenant_wrapper
            )
            logger.info("[userbot] Natija: %s", result.get("status"))
            if result.get("status") == "approved":
                await _notify_tenant_payment_approved(result)
        except Exception:
            logger.exception("[userbot] Xabarni qayta ishlashda xatolik.")

    @client.on(events.NewMessage())
    async def handler(event):
        await process_message(event.message)

    # Deploy paytida yoki kuzatuvchi vaqtincha o'chib qolganida kelgan to'lov
    # yo'qolib ketmasin. Deduplikatsiya bir xabarni ikki marta tasdiqlashga yo'l
    # qo'ymaydi; faqat oxirgi 20 ta xabar tekshiriladi.
    try:
        async for old_message in client.iter_messages(CARD_BOT_USERNAME, limit=20):
            await process_message(old_message)
    except Exception:
        logger.exception("[userbot] Oxirgi to'lov xabarlarini tekshirib bo'lmadi.")

    logger.info("[userbot] Tinglashni boshladi.")
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
