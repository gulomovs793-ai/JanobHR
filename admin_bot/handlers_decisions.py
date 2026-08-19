"""
Admin bot — nomzodni "Suhbatga chaqirish" / "Rad etish" qarori.

Tugmalar Admin bot orqali yuborilgani uchun, ularni bosish natijasi ham shu
bot dispatcher'iga keladi. Nomzodga xabar berish uchun esa NOMZOD-BOT
kerak (chunki nomzod faqat o'sha bot bilan suhbatlashgan) — shu sababli
services/bot_registry orqali ikkinchi bot instansiyasidan foydalanamiz.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from i18n import DEFAULT_LANG, t
from services import bot_registry, database

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_decisions")


@router.callback_query(F.data.startswith("decision:"))
async def handle_decision(callback: CallbackQuery):
    _, action, app_id_str = callback.data.split(":")
    app_id = int(app_id_str)

    app = await database.get_application(app_id)
    if not app:
        await callback.answer("Anketa topilmadi.", show_alert=True)
        return

    if app["status"] != "pending":
        await callback.answer("Bu anketa bo'yicha qaror allaqachon qabul qilingan.", show_alert=True)
        return

    lang = app.get("lang", DEFAULT_LANG)

    if action == "accept":
        new_status = "accepted"
        result_label = "✅ Suhbatga chaqirildi"
    else:
        new_status = "declined"
        result_label = "❌ Rad etildi"

    await database.update_status(app_id, new_status)

    candidate_bot = bot_registry.candidate_bot
    if candidate_bot:
        try:
            if action == "accept":
                from handlers.sell import send_slot_offer

                await send_slot_offer(
                    candidate_bot, app["user_id"], app_id,
                    t("decision_accept_intro", lang), lang,
                )
            else:
                await candidate_bot.send_message(
                    chat_id=app["user_id"], text=t("decision_decline_text", lang)
                )
        except Exception:
            logger.exception("Nomzodga xabar yuborib bo'lmadi (user_id=%s).", app["user_id"])
    else:
        logger.warning("Nomzod-bot topilmadi — %s uchun natija xabari yuborilmadi.", app["user_id"])

    await callback.answer(result_label)

    # Shu administratorning o'z nusxasidagi xabarni yangilaymiz. (Agar bir nechta
    # administrator bo'lsa, ularning boshqa nusxalari o'zgarishsiz qoladi, lekin
    # ular bosishga urinsa, yuqoridagi "allaqachon qabul qilingan" tekshiruvi
    # ularni to'xtatadi.)
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
