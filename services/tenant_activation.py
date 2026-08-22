"""
Mijozni faollashtirish. ENDI WEBHOOK KERAK EMAS — hammasi bitta jarayonda,
polling orqali ishlaydi. Faollashtirish shunchaki mijoz holatini "active"
qilishdan iborat: `bot.py`dagi tenant_manager har ~20 soniyada faol
mijozlarni tekshirib, yangi faollashganini avtomatik topib, ikkala botini
(nomzod + admin) ishga tushiradi — qo'shimcha qadam kerak emas.

Bu funksiya ikki joydan chaqiriladi: founder_panel.py (qo'lda tugma) va
services/payment_automation.py (avtomatik to'lov aniqlanganda).
"""
import logging

from aiogram import Bot

from services import database

logger = logging.getLogger("janob_hr_bot")


async def activate_tenant(tenant_id: int) -> dict:
    """Mijozni faollashtiradi. Muvaffaqiyatli bo'lsa
    {"ok": True, "candidate_username": ..., "admin_username": ...} qaytaradi."""
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        return {"ok": False, "error": "Mijoz topilmadi."}

    cand_bot = None
    admin_bot = None
    try:
        cand_bot = Bot(token=tenant["bot_token"])
        cand_me = await cand_bot.get_me()

        admin_bot = Bot(token=tenant["admin_bot_token"])
        admin_me = await admin_bot.get_me()
    except Exception:
        logger.exception("Mijoz (id=%s) tokenlarini tekshirib bo'lmadi.", tenant_id)
        return {"ok": False, "error": "Token(lar) endi ishlamayapti — qayta tekshiring."}
    finally:
        if cand_bot is not None:
            await cand_bot.session.close()
        if admin_bot is not None:
            await admin_bot.session.close()

    await database.update_tenant_status(tenant_id, "active", bot_username=cand_me.username)
    await database.set_admin_bot_username(tenant_id, admin_me.username)

    logger.info(
        "Mijoz faollashtirildi: id=%s, %s (nomzod=@%s, admin=@%s). Botlar ~20 soniyada ishga tushadi.",
        tenant_id, tenant["company_name"], cand_me.username, admin_me.username,
    )

    if tenant["admin_user_ids"]:
        try:
            notify_bot = Bot(token=tenant["admin_bot_token"])
            await notify_bot.send_message(
                chat_id=tenant["admin_user_ids"][0],
                text=(
                    "🎉 Botlaringiz faollashtirildi! Bir necha soniyada ishga tushadi.\n\n"
                    f"Admin panel: @{admin_me.username}\nNomzod-bot: @{cand_me.username}"
                ),
            )
            await notify_bot.session.close()
        except Exception:
            logger.exception("Mijozga faollashtirish xabarini yuborib bo'lmadi (tenant_id=%s).", tenant_id)

    return {"ok": True, "candidate_username": cand_me.username, "admin_username": admin_me.username}


async def notify_founder_admin_panel(text: str) -> None:
    """Asoschiga (SIZGA) yangi buyurtma/to'lov haqida xabar beradi — ALOHIDA
    Founder Bot orqali EMAS, balki sizning o'z (asosiy kompaniyangiz)
    Admin-panel botingiz orqali, chunki siz allaqachon shu botni ishlatib
    turibsiz va unga /start yubourgansiz."""
    from config import BOT_TOKEN

    founder_tenant = await database.get_tenant_by_token(BOT_TOKEN)
    if not founder_tenant or not founder_tenant.get("admin_bot_token"):
        logger.warning("Asoschi (o'z) tenant yoki uning admin-boti topilmadi — xabar yuborilmadi: %s", text[:200])
        return

    bot = Bot(token=founder_tenant["admin_bot_token"])
    for admin_id in founder_tenant["admin_user_ids"]:
        try:
            await bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Asoschiga (admin_id=%s) xabar yuborib bo'lmadi.", admin_id)
    await bot.session.close()
