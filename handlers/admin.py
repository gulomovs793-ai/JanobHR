"""
Janob HR Bot — anketa matnini formatlash va uni tegishli mijozning
administratorlariga yuborish.

KO'P MIJOZLI: har bir mijozda nomzod-bot va admin panel-bot alohida.
Anketa va qaror tugmalari admin-bot orqali yuboriladi; nomzod yuborgan media
esa nomzod-botdan yuklab olinib, admin-botga qayta yuklanadi.
"""

import logging
from html import escape
from io import BytesIO

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database
from services.ai_scoring import aggregate_scores, get_ai_unavailable_keys
from vacancies import build_questions

logger = logging.getLogger("janob_hr_bot")

_VERDICT_EMOJI = {"yashil": "🟢", "sariq": "🟡", "qizil": "🔴"}

_RED_FLAG_LABELS = {
    "qurbon_sindromi": "Qurbon sindromi (aybni boshqaga yuklaydi)",
    "abstrakt_javob": "Abstrakt javob (aniq raqam/qadam yo'q)",
    "narsissizm": 'Ortiqcha "men"chilik (jamoa hissasini tan olmaydi)',
    "ai_yozgan": "⚠️ AI/ChatGPT orqali yozilgan bo'lishi shubhali",
    "natija_isbotsiz": "Natija aniq dalil yoki raqam bilan tasdiqlanmagan",
    "tajriba_shubhali": "Amaliy tajriba bo'yicha aniqlashtirish kerak",
    "tez_tez_ish_almashtirish": "Ish joylarini tez-tez almashtirish signali",
    "javob_zid": "Javob ichida bir-biriga zid ma'lumot bor",
    "maosh_budgetdan_yuqori": "Kutilayotgan maosh vakansiya budjetidan yuqori",
}

# Telegram oddiy matnli xabarlar uchun 4096 belgigacha ruxsat beradi (rasm/fayl/video
# caption'lari uchun esa atigi 1024). Shu sabab, to'liq tahlilni HAR DOIM alohida
# oddiy xabar sifatida yuboramiz (fayl/video caption'iga emas) va xavfsizlik uchun
# shu chegaradan pastroq qilib qisqartiramiz.
_MAX_TEXT_LENGTH = 3800


def format_candidate_card(app: dict) -> str:
    ai_scores = app.get("ai_scores") or {}
    aggregate = aggregate_scores(ai_scores)
    unavailable_keys = get_ai_unavailable_keys(ai_scores)
    scored = [
        value
        for value in ai_scores.values()
        if isinstance(value, dict) and isinstance(value.get("score"), (int, float))
    ]
    strongest = max(scored, key=lambda value: value["score"], default=None)
    weakest = min(scored, key=lambda value: value["score"], default=None)
    strength = (strongest or {}).get("evidence") or (strongest or {}).get("izoh") or "Javoblarini to'liq ko'rib chiqing."
    risk = "Aniq xavf aniqlanmadi."
    if aggregate and aggregate.get("red_flags"):
        risk = _RED_FLAG_LABELS.get(
            aggregate["red_flags"][0], aggregate["red_flags"][0]
        )
    elif weakest and weakest.get("score", 100) < 70:
        risk = weakest.get("izoh") or "Ayrim javoblari yetarlicha aniq emas."

    if unavailable_keys:
        ai_note = f"⚠️ AI tahlili {len(unavailable_keys)} ta savolda ishlamadi."
        risk = f"{ai_note} {risk}"
        if aggregate:
            score = f"{aggregate['avg_score']}/100 ⚠️ qisman"
        else:
            score = "⚠️ AI ishlamadi"
            strength = "AI tahlili mavjud emas — javoblarni qo'lda ko'ring."
    else:
        score = f"{aggregate['avg_score']}/100" if aggregate else "Baholanmagan"
    return (
        f"👤 <b>{escape(str(app['full_name']))}</b>\n"
        f"💼 {escape(str(app['vacancy_title']))}\n"
        f"🎯 Moslik: <b>{score}</b>\n"
        f"📱 <code>{escape(str(app.get('phone_number') or '—'))}</code>\n\n"
        f"<b>Kuchli tomoni:</b> {escape(str(strength))}\n"
        f"<b>Xavf:</b> {escape(str(risk))}"
    )


async def format_application_full_text(app: dict) -> str:
    lines = [
        f"🆕 <b>Yangi anketa</b> — {escape(str(app['vacancy_title']))}",
        (
            f"👤 {escape(str(app['full_name']))} "
            f"(@{escape(str(app['username'] or '—'))}, id: {app['user_id']})"
        ),
    ]
    if app.get("phone_number"):
        lines.append(f"📞 {escape(str(app['phone_number']))}")
    if app.get("lang") == "ru":
        lines.append("🌐 Til: Rus tilida murojaat qilgan")
    lines.append("")

    ai_scores = app.get("ai_scores") or {}
    unavailable_keys = get_ai_unavailable_keys(ai_scores)
    tenant_id = app["tenant_id"]

    for key, value in app["answers"].items():
        text = escape(str(value))
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
                lines.append(f"   ↳ {emoji} <i>{score_part}{escape(izoh)}</i>")
                evidence = str(result.get("evidence") or "").strip()
                if evidence:
                    lines.append(f"      <b>Dalil:</b> {escape(evidence)}")

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
        if unavailable_keys or valid_count < len(expected_keys):
            missing_count = max(len(expected_keys) - valid_count, len(unavailable_keys))
            lines.append(
                f"⚠️ <b>AI tahlili to'liq emas:</b> {missing_count} ta savolni "
                "qo'lda ko'rib chiqing."
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

    text = format_candidate_card(app)
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Suhbatga chaqirish", callback_data=f"decision:accept:{app_id}"
    )
    builder.button(text="🟡 Keyin ko'rish", callback_data=f"decision:save:{app_id}")
    builder.button(text="❌ Rad etish", callback_data=f"decision:reject:{app_id}")
    builder.button(text="📋 To'liq javoblar", callback_data=f"apps:full:{app_id}:all:0")
    builder.adjust(2, 1, 1)

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
                    chat_id=admin_id,
                    text=text,
                    reply_markup=builder.as_markup(),
                    parse_mode=ParseMode.HTML,
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
        f"📅 <b>{escape(str(app['full_name']))}</b> "
        f"(@{escape(str(app['username'] or '—'))}) suhbat uchun "
        f"vaqtni tanladi: <b>{escape(str(slot))}</b>"
    )
    admin_bot = Bot(token=tenant["admin_bot_token"])
    try:
        for admin_id in tenant["admin_user_ids"]:
            try:
                await admin_bot.send_message(
                    chat_id=admin_id, text=text, parse_mode=ParseMode.HTML
                )
            except Exception:
                logger.exception(
                    "Admin (id=%s) ga vaqt tanlovi haqida xabar berib bo'lmadi.",
                    admin_id,
                )
    finally:
        await admin_bot.session.close()
