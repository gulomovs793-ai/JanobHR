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
    CARD_BOT_USERNAME, TELEGRAM_API_HASH,
    TELEGRAM_API_ID, TELEGRAM_USERBOT_SESSION,
)
from services import database
from services.payment_automation import handle_payment_notification
from services.tenant_activation import activate_tenant

logger = logging.getLogger("janob_hr_userbot")


def is_userbot_configured() -> bool:
    return bool(TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USERBOT_SESSION)


async def _notify_founders(text: str):
    """Asoschiga xabar yuborish — endi ALOHIDA Founder Bot orqali EMAS,
    balki asoschining o'z Admin-panel boti orqali (chunki u allaqachon
    ishlatilayotgan, tanish bot)."""
    from services.tenant_activation import notify_founder_admin_panel

    await notify_founder_admin_panel(text)


async def _activate_tenant_wrapper(tenant_id: int):
    result = await activate_tenant(tenant_id)
    if not result["ok"]:
        raise RuntimeError(result["error"])


async def start_userbot():
    if not is_userbot_configured():
        logger.info("[userbot] Sozlanmagan (TELEGRAM_API_ID/HASH/SESSION yo'q) — o'tkazib yuborildi.")
        return

    client = TelegramClient(
        StringSession(TELEGRAM_USERBOT_SESSION), TELEGRAM_API_ID, TELEGRAM_API_HASH,
        connection_retries=10, retry_delay=3, auto_reconnect=True,
    )
    await client.connect()

    me = await client.get_me()
    uname = f"@{me.username}" if getattr(me, "username", None) else "(username yo'q)"
    expected = CARD_BOT_USERNAME.lower()
    logger.info("[userbot] Ulandi: %s. Kuzatilayotgan bot: @%s", uname, expected)

    @client.on(events.NewMessage())
    async def handler(event):
        try:
            text = (event.message.message or "").strip()
            if not text:
                return

            # --- ENG MUHIM HIMOYA: faqat aynan shu botdan kelgan xabar qabul qilinadi ---
            sender = await event.get_sender()
            sender_username = (getattr(sender, "username", "") or "").lower()
            if not sender_username or sender_username != expected:
                return
            if not getattr(sender, "bot", False):
                logger.warning("[userbot] @%s bot emas — e'tiborsiz qoldirildi.", sender_username)
                return

            logger.info("[userbot] @%s dan xabar keldi (%d belgi).", expected, len(text))
            result = await handle_payment_notification(text, _notify_founders, _activate_tenant_wrapper)
            logger.info("[userbot] Natija: %s", result.get("status"))
        except Exception:
            logger.exception("[userbot] Xabarni qayta ishlashda xatolik.")

    logger.info("[userbot] Tinglashni boshladi.")
    await client.run_until_disconnected()


async def main():
    await database.init_db()
    await start_userbot()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    asyncio.run(main())
