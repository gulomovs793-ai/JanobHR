"""Janob HR Bot — admin guruhga anketa yuborish va qaror (qabul/rad) tugmalari."""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_GROUP_ID
from services import database
from services.ai_scoring import aggregate_scores

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin")

_VERDICT_EMOJI = {"yashil": "🟢", "sariq": "🟡", "qizil": "🔴"}

_RED_FLAG_LABELS = {
    "qurbon_sindromi": "Qurbon sindromi (aybni boshqaga yuklaydi)",
    "abstrakt_javob": "Abstrakt javob (aniq raqam/qadam yo'q)",
    "narsissizm": "Ortiqcha \"men\"chilik (jamoa hissasini tan olmaydi)",
}

# Telegram oddiy matnli xabarlar uchun 4096 belgigacha ruxsat beradi (rasm/fayl/video
# caption'lari uchun esa atigi 1024). Shu sabab, to'liq tahlilni HAR DOIM alohida
# oddiy xabar sifatida yuboramiz (fayl/video caption'iga emas) va xavfsizlik uchun
# shu chegaradan pastroq qilib qisqartiramiz.
_MAX_TEXT_LENGTH = 3800


def _format_application_text(app: dict) -> str:
    lines = [
        f"🆕 <b>Yangi anketa</b> — {app['vacancy_title']}",
        f"👤 {app['full_name']} (@{app['username'] or '—'}, id: {app['user_id']})",
        "",
    ]
    for value in app["answers"].values():
        text = str(value)
        # Bitta javob juda uzun bo'lib qolsa (masalan nomzod juda batafsil yozsa),
        # xabar limitidan chiqib ketmasligi uchun qisqartiramiz.
        if len(text) > 500:
            text = text[:500] + "…"
        lines.append(f"• {text}")

    ai_scores = app.get("ai_scores") or {}
    aggregate = aggregate_scores(ai_scores)

    if aggregate:
        emoji = _VERDICT_EMOJI.get(aggregate["verdict"], "⚪")
        lines.append("")
        lines.append(f"{emoji} <b>Yakuniy AI ball: {aggregate['avg_score']}/100</b>")

        if aggregate["red_flags"]:
            flag_labels = [_RED_FLAG_LABELS.get(f, f) for f in aggregate["red_flags"]]
            lines.append("🚩 Bayroqlar: " + "; ".join(flag_labels))

        notes = [
            v.get("izoh", "").strip()
            for v in ai_scores.values()
            if isinstance(v, dict) and v.get("izoh", "").strip()
        ]
        seen = []
        for note in notes:
            if note not in seen:
                seen.append(note)
        if seen:
            lines.append("🤖 AI izohi: " + " / ".join(seen[:3]))

    if app.get("selected_slot"):
        lines.append(f"📅 Nomzod tanlagan vaqt: {app['selected_slot']}")

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_LENGTH:
        text = text[:_MAX_TEXT_LENGTH] + "\n\n… (xabar qisqartirildi, to'liq matn bazada saqlangan)"
    return text


async def notify_admin_group(bot, app_id: int):
    if not ADMIN_GROUP_ID:
        logger.warning("ADMIN_GROUP_ID sozlanmagan, anketa admin guruhga yuborilmadi.")
        return

    app = await database.get_application(app_id)
    if not app:
        return

    chat_id = int(ADMIN_GROUP_ID)

    # 1) Fayl (agar bo'lsa) — QISQA caption bilan, tugmasiz. Telegram caption
    #    uzunligi atigi 1024 belgi bilan cheklangani uchun to'liq tahlilni bu
    #    yerga sig'dirishga urinmaymiz.
    if app.get("resume_file_id"):
        try:
            await bot.send_document(
                chat_id=chat_id,
                document=app["resume_file_id"],
                caption=f"📄 {app['full_name']} — {app['vacancy_title']}",
            )
        except Exception:
            logger.exception("Rezyume faylini yuborib bo'lmadi (app_id=%s).", app_id)
    elif app.get("video_file_id"):
        try:
            await bot.send_video(
                chat_id=chat_id,
                video=app["video_file_id"],
                caption=f"🎥 {app['full_name']} — {app['vacancy_title']}",
            )
        except Exception:
            logger.exception("Video-vizitkani yuborib bo'lmadi (app_id=%s).", app_id)

    # 2) To'liq tahlil + qaror tugmalari — HAR DOIM alohida oddiy xabar sifatida
    #    (4096 belgigacha joy bor).
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Suhbatga chaqirish", callback_data=f"decision:accept:{app_id}")
    builder.button(text="❌ Rad etish", callback_data=f"decision:reject:{app_id}")
    builder.adjust(2)

    sent = await bot.send_message(
        chat_id=chat_id,
        text=_format_application_text(app),
        reply_markup=builder.as_markup(),
    )

    await database.set_admin_message(app_id, sent.message_id)


async def notify_admin_slot_selected(bot, app_id: int, slot: str):
    """Nomzod suhbat vaqtini tanlaganda admin guruhga qisqa xabar yuboradi."""
    if not ADMIN_GROUP_ID:
        return

    app = await database.get_application(app_id)
    if not app:
        return

    await bot.send_message(
        chat_id=int(ADMIN_GROUP_ID),
        text=(
            f"📅 <b>{app['full_name']}</b> (@{app['username'] or '—'}) suhbat uchun "
            f"vaqtni tanladi: <b>{slot}</b>"
        ),
    )


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

    if action == "accept":
        new_status = "accepted"
        candidate_text = (
            "🎉 Tabriklaymiz! Sizning nomzodingiz ma'qullandi — tez orada suhbat vaqti "
            "haqida siz bilan bog'lanamiz."
        )
        result_label = "✅ Suhbatga chaqirildi"
    else:
        new_status = "declined"
        candidate_text = (
            "Vaqt ajratganingiz uchun rahmat. Hozircha ushbu lavozim bo'yicha boshqa "
            "nomzodni tanladik. Kelajakda boshqa vakansiyalarimizni kuzatib boring!"
        )
        result_label = "❌ Rad etildi"

    await database.update_status(app_id, new_status)

    try:
        await callback.bot.send_message(chat_id=app["user_id"], text=candidate_text)
    except Exception:
        logger.exception("Nomzodga xabar yuborib bo'lmadi (user_id=%s).", app["user_id"])

    await callback.answer(result_label)

    try:
        base_caption = callback.message.caption or callback.message.text or ""
        new_text = f"{base_caption}\n\n{result_label}"
        if len(new_text) > 4096:
            new_text = new_text[:4090] + "…"
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=new_text)
        else:
            await callback.message.edit_text(new_text)
    except Exception:
        logger.exception("Admin xabarini yangilab bo'lmadi (app_id=%s).", app_id)
