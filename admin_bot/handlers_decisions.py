"""
Admin bot — nomzodni "Suhbatga chaqirish" / "Rad etish" qarori.

KO'P MIJOZLI: bu — mijozning Admin panel-botida bosiladi, lekin nomzodga
xabar berish uchun O'SHA MIJOZNING NOMZOD-BOTI kerak (chunki nomzod faqat
o'sha bot bilan suhbatlashgan). Ikkalasi endi mustaqil, alohida token bilan
ishlagani uchun, shu yerda tenant yozuvidagi `bot_token`dan vaqtinchalik
Bot obyekti yasab, xabar yuboramiz.
"""

import logging

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from i18n import DEFAULT_LANG, t
from services import database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_decisions")


@router.callback_query(F.data.startswith("decision:"))
async def handle_decision(callback: CallbackQuery, tenant_id: int, tenant: dict):
    _, action, app_id_str = callback.data.split(":")
    app_id = int(app_id_str)

    app = await database.get_application(tenant_id, app_id)
    if not app:
        await callback.answer("Anketa topilmadi.", show_alert=True)
        return

    if app["status"] != "pending":
        await callback.answer(
            "Bu anketa bo'yicha qaror allaqachon qabul qilingan.", show_alert=True
        )
        return

    lang = app.get("lang", DEFAULT_LANG)

    if action == "accept":
        new_status = "accepted"
        result_label = "✅ Suhbatga chaqirildi"
    else:
        new_status = "declined"
        result_label = "❌ Rad etildi"

    await database.update_status(tenant_id, app_id, new_status)

    candidate_bot = Bot(token=tenant["bot_token"])
    try:
        if action == "accept":
            from handlers.sell import send_slot_offer

            await send_slot_offer(
                candidate_bot,
                tenant_id,
                app["user_id"],
                app_id,
                t("decision_accept_intro", lang),
                lang,
            )
        else:
            await candidate_bot.send_message(
                chat_id=app["user_id"], text=t("decision_decline_text", lang)
            )
    except Exception:
        logger.exception(
            "Nomzodga xabar yuborib bo'lmadi (user_id=%s).", app["user_id"]
        )
    finally:
        await candidate_bot.session.close()

    await callback.answer(result_label)

    try:
        base_text = callback.message.text or callback.message.caption or ""
        new_text = f"{base_text}\n\n{result_label}"
        if len(new_text) > 4096:
            new_text = new_text[:4090] + "…"
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=new_text)
        else:
            await callback.message.edit_text(new_text)
    except Exception:
        logger.exception("Admin xabarini yangilab bo'lmadi (app_id=%s).", app_id)
