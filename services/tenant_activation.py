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
    from webhook_app import configure_admin_miniapp, register_new_tenant_webhook

    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Mijoz topilmadi."}

    # Amaldagi mijoz tarifini uzaytirayotganda botlar allaqachon ishlayapti.
    # Polling rejimida WEBHOOK_BASE_URL bo'lmaydi; webhookni qayta o'rnatishga
    # urinish to'g'ri to'lovni xato deb belgilab qo'yardi.
    if tenant["status"] == "active":
        return {
            "ok": True,
            "candidate_username": tenant.get("bot_username") or "",
            "admin_username": tenant.get("admin_bot_username") or "",
        }

    try:
        cand_username = await register_new_tenant_webhook(tenant["bot_token"])
        admin_username = await register_new_tenant_webhook(tenant["admin_bot_token"])
    except Exception:
        logger.exception("Mijoz (id=%s) webhooklarini ornatib bolmadi.", tenant_id)
        return {
            "ok": False,
            "error": "Webhook o'rnatishda xato — tokenlar to'g'riligini tekshiring.",
        }

    await database.update_tenant_status(tenant_id, "active", bot_username=cand_username)
    await database.set_admin_bot_username(tenant_id, admin_username)
    tenant["id"] = tenant_id
    await configure_admin_miniapp(tenant)

    if tenant["admin_user_ids"]:
        notify_bot = Bot(token=tenant["admin_bot_token"])
        try:
            await notify_bot.send_message(
                chat_id=tenant["admin_user_ids"][0],
                text=(
                    "🎉 Botlaringiz faollashtirildi! Endi to'liq ishlatishingiz mumkin.\n\n"
                    f"Admin panel: @{admin_username}\nNomzod-bot: @{cand_username}"
                ),
            )
        except Exception:
            logger.exception(
                "Mijozga faollashtirish xabarini yuborib bo'lmadi (tenant_id=%s).",
                tenant_id,
            )
        finally:
            await notify_bot.session.close()

    return {
        "ok": True,
        "candidate_username": cand_username,
        "admin_username": admin_username,
    }
