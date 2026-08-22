"""
Mijozni faollashtirish — ikkala bot uchun webhook o'rnatish va unga xabar
berish. Bu funksiya IKKI joydan chaqiriladi:
  1. founder_panel.py — asoschi qo'lda "Faollashtirish" tugmasini bosganda.
  2. services/payment_automation.py — to'lov avtomatik aniqlanganda.

Ikkalasi ham BIR XIL natijaga erishishi kerak, shuning uchun mantiq shu
yerda, bir joyda saqlanadi.
"""
import logging

from aiogram import Bot

from services import database

logger = logging.getLogger("janob_hr_bot")


async def activate_tenant(tenant_id: int) -> dict:
    """Mijozni faollashtiradi: ikkala bot uchun webhook o'rnatadi, holatini
    "active" qiladi va mijozning o'ziga xabar beradi.

    Muvaffaqiyatli bo'lsa {"ok": True, "candidate_username": ..., "admin_username": ...}
    qaytaradi, aks holda {"ok": False, "error": ...}.
    """
    from webhook_app import register_new_tenant_webhook

    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Mijoz topilmadi."}

    try:
        cand_username = await register_new_tenant_webhook(tenant["bot_token"])
        admin_username = await register_new_tenant_webhook(tenant["admin_bot_token"])
    except Exception:
        logger.exception("Mijoz (id=%s) webhooklarini ornatib bolmadi.", tenant_id)
        return {"ok": False, "error": "Webhook o'rnatishda xato — tokenlar to'g'riligini tekshiring."}

    await database.update_tenant_status(tenant_id, "active", bot_username=cand_username)
    await database.set_admin_bot_username(tenant_id, admin_username)

    if tenant["admin_user_ids"]:
        try:
            notify_bot = Bot(token=tenant["admin_bot_token"])
            await notify_bot.send_message(
                chat_id=tenant["admin_user_ids"][0],
                text=(
                    "🎉 Botlaringiz faollashtirildi! Endi to'liq ishlatishingiz mumkin.\n\n"
                    f"Admin panel: @{admin_username}\nNomzod-bot: @{cand_username}"
                ),
            )
            await notify_bot.session.close()
        except Exception:
            logger.exception("Mijozga faollashtirish xabarini yuborib bo'lmadi (tenant_id=%s).", tenant_id)

    return {"ok": True, "candidate_username": cand_username, "admin_username": admin_username}
