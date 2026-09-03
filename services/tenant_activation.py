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
    """Provision BOTH bots completely, then mark a new tenant active.

    Critical invariant: a pending tenant is never committed as ``active`` until
    candidate webhook, admin webhook and Admin Mini App configuration all
    succeeded. Existing active tenants are reconciled idempotently on retry.
    """
    from webhook_app import configure_admin_miniapp, register_new_tenant_webhook

    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Mijoz topilmadi."}
    if not tenant.get("bot_token") or not tenant.get("admin_bot_token"):
        return {"ok": False, "error": "Nomzod yoki admin bot tokeni yetishmayapti."}

    try:
        cand_username = await register_new_tenant_webhook(tenant["bot_token"])
        admin_username = await register_new_tenant_webhook(tenant["admin_bot_token"])
        prepared = dict(tenant)
        prepared["id"] = tenant_id
        prepared["bot_username"] = cand_username
        prepared["admin_bot_username"] = admin_username
        await configure_admin_miniapp(prepared)
    except Exception:
        logger.exception("Mijoz (id=%s) provisioningini yakunlab bo'lmadi.", tenant_id)
        return {
            "ok": False,
            "error": "Botlarni to'liq sozlashda xato — token/webhook/Mini Appni tekshiring.",
        }

    # DB commit is deliberately last. If anything above fails, a NEW tenant
    # remains pending and the next retry can safely reconcile everything.
    await database.set_admin_bot_username(tenant_id, admin_username)
    if tenant.get("status") != "active" or tenant.get("bot_username") != cand_username:
        await database.update_tenant_status(
            tenant_id, "active", bot_username=cand_username
        )

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
