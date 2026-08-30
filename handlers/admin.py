"""
Janob HR Bot — anketa matnini formatlash va uni tegishli mijozning
administratorlariga yuborish.

KO'P MIJOZLI: har bir mijozda nomzod-bot va admin panel-bot alohida.
Anketa va qaror tugmalari admin-bot orqali yuboriladi; nomzod yuborgan media
esa nomzod-botdan yuklab olinib, admin-botga qayta yuklanadi.
"""

import logging
from io import BytesIO

from aiogram import Bot
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database
from services.ai_scoring import aggregate_scores
from vacancies import build_questions

logger = logging.getLogger("janob_hr_bot")

_VERDICT_EMOJI = {"yashil": "🟢", "sariq": "🟡", "qizil": "🔴"}

_RED_FLAG_LABELS = {
    "qurbon_sindromi": "Qurbon sindromi (aybni boshqaga yuklaydi)",
    "abstrakt_javob": "Abstrakt javob (aniq raqam/qadam yo'q)",
    "narsissizm": 'Ortiqcha "men"chilik (jamoa hissasini tan olmaydi)',
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
    tenant_id = app["tenant_id"]

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

    vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
    expected_keys = (
        [q["key"] for q in build_questions(vacancy) if q.get("ai_score")]
        if vacancy
        else []
    )
    valid_count = sum(
        1
        for k in expected_keys
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
        coverage = (
            f" ({valid_count}/{len(expected_keys)} savol tahlil qilindi)"
            if valid_count < len(expected_keys)
            else ""
        )
        lines.append(
            f"{emoji} <b>Yakuniy AI ball: {aggregate['avg_score']}/100</b>{coverage}"
        )
        lines.append(
            f"📊 Natijadorlik: {aggregate['avg_natijadorlik']} | "
            f"Mas'uliyat: {aggregate['avg_masuliyat']} | "
            f"Aniqlik: {aggregate['avg_aniqlik']}"
        )

        if aggregate["red_flags"]:
            flag_labels = [_RED_FLAG_LABELS.get(f, f) for f in aggregate["red_flags"]]
            lines.append("🚩 Bayroqlar: " + "; ".join(flag_labels))

    suspect_keys = app.get("ai_suspect_flags") or []
    if suspect_keys and vacancy:
        key_to_text = {q["key"]: q["text"] for q in build_questions(vacancy)}
        total_ai_questions = len(expected_keys) or len(suspect_keys)
        percent = (
            round(100 * len(suspect_keys) / total_ai_questions)
            if total_ai_questions
            else 0
        )
        lines.append("")
        lines.append(
            f"🤖⚠️ <b>AI orqali yozilgan deb gumon qilingan: {len(suspect_keys)}/"
            f"{total_ai_questions} savol (~{percent}%)</b>"
        )
        lines.append(
            "(nomzod qayta so'ralganda tuzatgan bo'lishi mumkin, lekin bu shubha qayd etildi)"
        )
        for k in suspect_keys:
            q_text = key_to_text.get(k, k)
            short = q_text if len(q_text) <= 70 else q_text[:70] + "…"
            lines.append(f"   • {short}")

    if app.get("selected_slot"):
        lines.append(f"📅 Nomzod tanlagan vaqt: {app['selected_slot']}")

    text = "\n".join(lines)
    if len(text) > _MAX_TEXT_LENGTH:
        text = (
            text[:_MAX_TEXT_LENGTH]
            + "\n\n… (xabar qisqartirildi, to'liq matn bazada saqlangan)"
        )
    return text


async def notify_admins(tenant_id: int, app_id: int, bot: Bot):
    """Anketani tenantning ADMIN botidan yuboradi.

    ``bot`` — nomzod-bot. Undagi file_id boshqa botda ishlamasligi mumkin,
    shuning uchun media avval yuklab olinib, admin-botga qayta yuklanadi.
    """
    tenant = await database.get_tenant(tenant_id)
    if not tenant or not tenant["admin_user_ids"] or not tenant.get("admin_bot_token"):
        logger.warning(
            "Mijoz (id=%s) uchun admin ID topilmadi — anketa hech kimga yuborilmadi (app_id=%s).",
            tenant_id,
            app_id,
        )
        return

    app = await database.get_application(tenant_id, app_id)
    if not app:
        return

    text = await _format_application_text(app)
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Suhbatga chaqirish", callback_data=f"decision:accept:{app_id}"
    )
    builder.button(text="❌ Rad etish", callback_data=f"decision:reject:{app_id}")
    builder.adjust(2)

    voice_answers = app.get("voice_answers") or {}
    voice_key_to_text: dict = {}
    if voice_answers:
        vacancy = await database.get_vacancy(tenant_id, app["vacancy_key"])
        if vacancy:
            voice_key_to_text = {q["key"]: q["text"] for q in build_questions(vacancy)}

    async def copy_file(file_id: str, filename: str) -> BufferedInputFile:
        downloaded: BytesIO = await bot.download(file_id)
        downloaded.seek(0)
        return BufferedInputFile(downloaded.read(), filename=filename)

    admin_bot = Bot(token=tenant["admin_bot_token"])
    try:
        for admin_id in tenant["admin_user_ids"]:
            try:
                if app.get("resume_file_id"):
                    await admin_bot.send_document(
                        chat_id=admin_id,
                        document=await copy_file(app["resume_file_id"], "resume.pdf"),
                        caption=f"📄 {app['full_name']} — {app['vacancy_title']}",
                    )
                elif app.get("video_file_id"):
                    await admin_bot.send_video(
                        chat_id=admin_id,
                        video=await copy_file(
                            app["video_file_id"], "candidate-video.mp4"
                        ),
                        caption=f"🎥 {app['full_name']} — {app['vacancy_title']}",
                    )

                for key, file_id in voice_answers.items():
                    q_text = voice_key_to_text.get(key, key)
                    short_q = q_text if len(q_text) <= 250 else q_text[:250] + "…"
                    try:
                        await admin_bot.send_voice(
                            chat_id=admin_id,
                            voice=file_id,
                            caption=f"🎙 {app['full_name']} — {short_q}",
                        )
                    except Exception:  # noqa: BLE001 - boshqa bot file_id'ni rad etishi kutiladi
                        # Voice file_id ham botga xos bo'lishi mumkin.
                        try:
                            await admin_bot.send_voice(
                                chat_id=admin_id,
                                voice=await copy_file(file_id, "answer.ogg"),
                                caption=f"🎙 {app['full_name']} — {short_q}",
                            )
                        except Exception:
                            logger.exception(
                                "Ovozli javobni adminga yuborib bo'lmadi (app_id=%s, key=%s).",
                                app_id,
                                key,
                            )

                sent = await admin_bot.send_message(
                    chat_id=admin_id, text=text, reply_markup=builder.as_markup()
                )
                await database.add_admin_message(
                    tenant_id, app_id, admin_id, sent.message_id
                )
            except Exception:
                logger.exception(
                    "Admin (id=%s) ga anketa yuborib bo'lmadi (app_id=%s, tenant=%s).",
                    admin_id,
                    app_id,
                    tenant_id,
                )
    finally:
        await admin_bot.session.close()


async def notify_admin_slot_selected(tenant_id: int, app_id: int, slot: str):
    tenant = await database.get_tenant(tenant_id)
    if not tenant or not tenant["admin_user_ids"]:
        return

    app = await database.get_application(tenant_id, app_id)
    if not app:
        return

    text = (
        f"📅 <b>{app['full_name']}</b> (@{app['username'] or '—'}) suhbat uchun "
        f"vaqtni tanladi: <b>{slot}</b>"
    )
    admin_bot = Bot(token=tenant["admin_bot_token"])
    try:
        for admin_id in tenant["admin_user_ids"]:
            try:
                await admin_bot.send_message(chat_id=admin_id, text=text)
            except Exception:
                logger.exception(
                    "Admin (id=%s) ga vaqt tanlovi haqida xabar berib bo'lmadi.",
                    admin_id,
                )
    finally:
        await admin_bot.session.close()
