"""ERROR darajasidagi log yozuvlarini founderning O'Z Admin panel-boti orqali
Telegramga yuboradi — shu paytgacha xatolar faqat server log'ida qolib,
ular haqida faqat mijoz shikoyat qilgandan keyin bilinardi.

Bir xil joydan (module:lineno) kelgan xato 5 daqiqada bir martadan ortiq
yuborilmaydi — sikl ichidagi xato spamning oldini olish uchun.
"""
import asyncio
import logging
import time

_COOLDOWN_SECONDS = 300
_last_sent: dict[str, float] = {}


class TelegramErrorHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.ERROR:
            return

        key = f"{record.module}:{record.lineno}"
        now = time.time()
        if now - _last_sent.get(key, 0) < _COOLDOWN_SECONDS:
            return
        _last_sent[key] = now

        try:
            text = self.format(record)
        except Exception:
            text = record.getMessage()

        # "message is not modified" — zararsiz, harakatga chaqirmaydigan xato
        # (kontent o'zgarmagan holda edit_text/edit_reply_markup chaqirilganda
        # Telegram shunday rad etadi). Founderni bezovta qilishning hojati yo'q.
        if "message is not modified" in text:
            return

        alert = f"🚨 <b>Xato</b> ({record.name}):\n<code>{text[:1500]}</code>"

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # event loop hali yo'q (masalan startup paytida) — jim qol
        loop.create_task(_send_alert(alert))


async def _send_alert(text: str) -> None:
    try:
        from services.tenant_activation import notify_founder_admin_panel
        await notify_founder_admin_panel(text)
    except Exception:
        pass  # xato haqida xabar yuborishning o'zi ham xato bersa — jim qol,
        # cheksiz sikl yaratmaslik uchun (logger.exception CHAQIRILMAYDI)
