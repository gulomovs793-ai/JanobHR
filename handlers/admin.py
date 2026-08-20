"""
Janob HR Bot — anketa matnini formatlash va uni Admin botga (har bir
administratorga shaxsiy xabar sifatida) yuborish.

Qaror (qabul/rad) tugmalarini bosish logikasi endi shu yerda EMAS —
u admin_bot/handlers_decisions.py'da, chunki tugmalar endi Admin bot orqali
yuboriladi va bosilganda javob ham o'sha bot dispatcher'iga keladi.
"""
import logging

from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_USER_IDS
from services import bot_registry, database
from services.ai_scoring import aggregate_scores
from vacancies import build_questions

logger = logging.getLogger("janob_hr_bot")

_VERDICT_EMOJI = {"yashil": "🟢", "sariq": "🟡", "qizil": "🔴"}

_RED_FLAG_LABELS = {
    "qurbon_sindromi": "Qurbon sindromi (aybni boshqaga yuklaydi)",
    "abstrakt_javob": "Abstrakt javob (aniq raqam/qadam yo'q)",
    "narsissizm": "Ortiqcha \"men\"chilik (jamoa hissasini tan olmaydi)",
    "ai_yozgan": "⚠️ AI/ChatGPT orqali yozilgan bo'lishi shubhali",
}

# Telegram oddiy matnli xabarlar uchun 4096 belgigacha ruxsat beradi (rasm/fayl/video
# caption'lari uchun esa atigi 1024). Shu sabab, to'liq tahlilni HAR DOIM alohida
# oddiy xabar sifatida yuboramiz (fayl/video caption'iga emas) va xavfsizlik uchun
# shu chegaradan pastroq qilib qisqartiramiz.
_MAX_TEXT_LENGTH = 3800


async def _format_application_text(app: dict) -> str:
    lines = [
        f"🆕 <b>Yangi anketa</b> — {app['vacancy_title']}",
        f"👤 {app['full_name']} (@{app['username'] or '—'}, id: {app['user_id']})",
    ]
    if app.get("phone_number"):
        lines.append(f"📞 {app['phone_number']}")
    if app.get("lang") == "ru":
        lines.append("🌐 Til: Rus tilida murojaat qilgan")
    lines.append("")

    ai_scores = app.get("ai_scores") or {}

    # Har bir javobni, agar AI shu savolni baholagan bo'lsa, aynan O'SHA javobning
    # tagida qisqa izoh bilan ko'rsatamiz — turli savollarga tegishli izohlarni
    # bitta qatorga aralashtirib qo'yish o'rniga (bu chalkash bo'lardi).
    for key, value in app["answers"].items():
        text = str(value)
        if len(text) > 500:
            text = text[:500] + "…"
        lines.append(f"• {text}")

        result = ai_scores.get(key)
        if isinstance(result, dict):
            izoh = result.get("izoh", "").strip()
            if izoh:
                emoji = _VERDICT_EMOJI.get(result.get("verdict"), "⚪")
                score = result.get("score")
                score_part = f"{score}/100 — " if score is not None else ""
                lines.append(f"   ↳ {emoji} <i>{score_part}{izoh}</i>")

    aggregate = aggregate_scores(ai_scores)

    vacancy = await database.get_vacancy(app["vacancy_key"])
    expected_keys = [q["key"] for q in build_questions(vacancy) if q.get("ai_score")] if vacancy else []
    valid_count = sum(
        1 for k in expected_keys
        if isinstance(ai_scores.get(k), dict) and "score" in ai_scores[k]
    )

    lines.append("")
    if expected_keys and not aggregate:
        lines.append(
            "⚠️ <b>AI tahlili amalga oshmadi</b> (API xatosi yoki limit tugagan bo'lishi "
            "mumkin) — javoblarni qo'lda ko'rib chiqing."
        )
    elif aggregate:
        emoji = _VERDICT_EMOJI.get(aggregate["verdict"], "⚪")
        coverage = f" ({valid_count}/{len(expected_keys)} savol tahlil qilindi)" if valid_count < len(expected_keys) else ""
        lines.append(f"{emoji} <b>Yakuniy AI ball: {aggregate['avg_score']}/100</b>{coverage}")
        lines.append(
            f"📊 Natijadorlik: {aggregate['avg_natijadorlik']} | "
            f"Mas'uliyat: {aggregate['avg_masuliyat']} | "
            f"Aniqlik: {aggregate['avg_aniqlik']}"
        )

        if aggregate["red_flags"]:
            flag_labels = [_RED_FLAG_LABELS.get(f, f) for f in aggregate["red_flags"]]
            lines.append("🚩 Bayroqlar: " + "; ".join(flag_labels))

    if app.get("selected_slot"):
        lines.append(f"📅 Nomzod tanlagan vaqt: {app['selected_slot']}")

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_LENGTH:
        text = text[:_MAX_TEXT_LENGTH] + "\n\n… (xabar qisqartirildi, to'liq matn bazada saqlangan)"
    return text


async def notify_admins(app_id: int):
    """Anketani Admin bot orqali har bir ADMIN_USER_IDS'dagi administratorga
    shaxsiy xabar sifatida yuboradi (guruh/kanal endi ishlatilmaydi)."""
    admin_bot = bot_registry.admin_bot

    if not admin_bot:
        logger.warning(
            "Admin bot ishga tushirilmagan (ADMIN_BOT_TOKEN sozlanmagan) — "
            "anketa hech kimga yuborilmadi (app_id=%s).", app_id,
        )
        return
    if not ADMIN_USER_IDS:
        logger.warning(
            "ADMIN_USER_IDS bo'sh — anketa hech kimga yuborilmadi (app_id=%s).", app_id,
        )
        return

    app = await database.get_application(app_id)
    if not app:
        return

    text = await _format_application_text(app)
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Suhbatga chaqirish", callback_data=f"decision:accept:{app_id}")
    builder.button(text="❌ Rad etish", callback_data=f"decision:reject:{app_id}")
    builder.adjust(2)

    for admin_id in ADMIN_USER_IDS:
        try:
            # 1) Fayl (agar bo'lsa) — QISQA caption bilan, tugmasiz.
            if app.get("resume_file_id"):
                await admin_bot.send_document(
                    chat_id=admin_id,
                    document=app["resume_file_id"],
                    caption=f"📄 {app['full_name']} — {app['vacancy_title']}",
                )
            elif app.get("video_file_id"):
                await admin_bot.send_video(
                    chat_id=admin_id,
                    video=app["video_file_id"],
                    caption=f"🎥 {app['full_name']} — {app['vacancy_title']}",
                )

            # 2) To'liq tahlil + qaror tugmalari.
            sent = await admin_bot.send_message(
                chat_id=admin_id, text=text, reply_markup=builder.as_markup(),
            )
            await database.add_admin_message(app_id, admin_id, sent.message_id)
        except Exception:
            logger.exception(
                "Admin (id=%s) ga anketa yuborib bo'lmadi (app_id=%s). Admin botga "
                "/start yuborganini tekshiring.", admin_id, app_id,
            )


async def notify_admin_slot_selected(app_id: int, slot: str):
    """Nomzod suhbat vaqtini tanlaganda Admin bot orqali barcha administratorlarga
    qisqa xabar yuboradi."""
    admin_bot = bot_registry.admin_bot
    if not admin_bot or not ADMIN_USER_IDS:
        return

    app = await database.get_application(app_id)
    if not app:
        return

    text = (
        f"📅 <b>{app['full_name']}</b> (@{app['username'] or '—'}) suhbat uchun "
        f"vaqtni tanladi: <b>{slot}</b>"
    )
    for admin_id in ADMIN_USER_IDS:
        try:
            await admin_bot.send_message(chat_id=admin_id, text=text)
        except Exception:
            logger.exception("Admin (id=%s) ga vaqt tanlovi haqida xabar berib bo'lmadi.", admin_id)
