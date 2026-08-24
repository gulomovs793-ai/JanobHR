"""Janob HR Bot — savol-javob oqimi, hard-filter, mavzuga aloqadorlik va AI baholash."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MAX_ANSWER_CHARS
from i18n import DEFAULT_LANG, t
from services import database
from services.ai_scoring import check_relevance, score_answer
from states import ApplyForm
from vacancies import is_negative_answer

logger = logging.getLogger("janob_hr_bot")

router = Router(name="questions")


async def ask_current_question(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    idx = data["question_index"]
    questions = data["vacancy_questions"]
    prefilled_keys = set(data.get("prefilled_from_resume", []))

    # Rezyumedan avtomatik to'ldirilgan (oddiy faktik) savollarni o'tkazib
    # yuboramiz — ular allaqachon `answers`da bor.
    while idx < len(questions) and questions[idx]["key"] in prefilled_keys:
        idx += 1
    if idx != data["question_index"]:
        await state.update_data(question_index=idx)

    if idx >= len(questions):
        await finish_questions(message, state)
        return

    total = len(questions)
    question_text = questions[idx]["text"]
    if questions[idx].get("voice"):
        question_text += t("voice_question_hint", lang)

    await message.answer(t("question_progress", lang, idx=idx + 1, total=total, text=question_text))
    await state.set_state(ApplyForm.answering_questions)


async def _reject_and_save(
    message: Message,
    state: FSMContext,
    data: dict,
    answers: dict,
    ai_scores: dict,
    reject_text: str,
    status: str,
):
    """Nomzodni xushmuomalalik bilan rad etadi, arizani baribir bazaga yozadi (statistika
    uchun) va suhbat holatini tozalaydi."""
    await message.answer(reject_text)
    await database.save_application(
        tenant_id=data["tenant_id"],
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=message.from_user.full_name,
        vacancy_key=data["vacancy_key"],
        vacancy_title=data["vacancy_title"],
        answers=answers,
        ai_scores=ai_scores,
        resume_file_id=None,
        video_file_id=None,
        status=status,
        lang=data.get("lang", DEFAULT_LANG),
        ai_suspect_flags=data.get("ai_suspect_flagged_keys", []),
        voice_answers=data.get("voice_answers", {}),
    )
    await state.clear()


# Oddiy faktik savollarda ("qaysi platforma/dastur ishlatasiz" kabi) bundan qisqa
# javoblar AI orqali tekshirilmaydi — bir so'zlik to'g'ri javoblarni ("Instagram",
# "Figma") noto'g'ri "aloqasiz" deb belgilash xavfini kamaytirish uchun.
_SHORT_ANSWER_SKIP_CHARS = 20

# AI ba'zan to'g'ri javoblarni ham noto'g'ri "aloqasiz" deb belgilashi mumkin —
# shuning uchun bitta xato tufayli butun arizani yo'qotmaslik uchun, nomzodga
# SHU SAVOLNI qayta javob berishga necha marta imkoniyat berilishi (ketma-ket
# necha marta "aloqasiz" chiqsa, arizani chindan rad etamiz).
_MAX_IRRELEVANT_RETRIES = 2

# Javob "ai_yozgan" (ChatGPT orqali yozilgan bo'lishi mumkin) deb belgilansa,
# nomzodga o'z so'zi bilan qayta yozish uchun cheklangan imkoniyat beriladi —
# bu ham 100% ishonchli aniqlash emas, shuning uchun darhol rad etmaymiz,
# lekin ketma-ket ikkinchi marta ham shubhali chiqsa, ariza rad etiladi.
_MAX_AI_SUSPECT_RETRIES = 1

# Javob mavzuga oid, lekin sifati past yoki abstrakt bo'lsa (aniq raqam/misolsiz),
# bot BITTA marta (har bir savol uchun ko'pi bilan bir marta) aniqlashtiruvchi
# savol beradi — bu nomzodga fikrini kengaytirish imkonini beradi, adminga esa
# to'liqroq ma'lumot bilan yetib boradi.
_FOLLOWUP_SCORE_THRESHOLD = 50


@router.message(ApplyForm.answering_questions, F.text)
async def handle_text_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    idx = data["question_index"]
    questions = data["vacancy_questions"]

    if questions[idx].get("voice"):
        # Bu savol MAJBURIY ravishda ovozli xabar talab qiladi — matn qabul qilinmaydi.
        await message.answer(t("voice_required", lang))
        return

    await _process_answer(message, state, message.text.strip())


@router.message(ApplyForm.answering_questions, F.voice)
async def handle_voice_answer(message: Message, state: FSMContext):
    """Ovozli javobni HECH QANDAY tahlil qilmasdan (matnga o'girmasdan) — xom
    audio fayl sifatida qabul qiladi. Fayl keyinroq Admin panelida to'g'ridan-
    to'g'ri tinglash uchun yuboriladi — baho AI emas, insonning o'zi tomonidan
    beriladi (bu ko'proq ishonchli, chunki nutqni-matnga o'girishga bog'liq emas)."""
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    idx = data["question_index"]
    questions = data["vacancy_questions"]
    q = questions[idx]

    voice_answers = data.get("voice_answers", {})
    voice_answers[q["key"]] = message.voice.file_id

    answers = data.get("answers", {})
    answers[q["key"]] = t("voice_answer_placeholder", lang)

    await state.update_data(
        voice_answers=voice_answers, answers=answers, question_index=idx + 1,
        irrelevant_retry_count=0, ai_suspect_retry_count=0,
    )
    await message.answer(t("voice_received", lang))
    await ask_current_question(message, state)


async def _process_answer(message: Message, state: FSMContext, answer_text: str):
    """Matnli javobni tahlil qiladi (aniqlik, ishonchlilik, mavzuga doirlik —
    mavjud AI baholash tizimi orqali)."""
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    idx = data["question_index"]
    questions = data["vacancy_questions"]
    q = questions[idx]

    if not answer_text:
        await message.answer(t("answer_empty", lang))
        return

    # --- Uzunlik chegarasi: juda uzun javoblar o'qishni va AI tahlilini qiyinlashtiradi ---
    if len(answer_text) > MAX_ANSWER_CHARS:
        await message.answer(t("answer_too_long", lang, length=len(answer_text), max=MAX_ANSWER_CHARS))
        return

    # --- Agar bu — oldin so'ralgan aniqlashtiruvchi savolga javob bo'lsa, uni
    # oldingi (abstrakt) javob o'rniga qo'yamiz va bir marta qayta baholaymiz. ---
    if data.get("awaiting_followup_for") == idx:
        answers = data.get("answers", {})
        ai_scores = data.get("ai_scores", {})
        answers[q["key"]] = answer_text

        result = await score_answer(q["text"], answer_text)
        if result is not None:
            ai_scores[q["key"]] = result

            if "ai_yozgan" in result.get("red_flags", []):
                flagged_keys = data.get("ai_suspect_flagged_keys", [])
                if q["key"] not in flagged_keys:
                    flagged_keys.append(q["key"])

                ai_suspect_count = data.get("ai_suspect_retry_count", 0) + 1
                if ai_suspect_count > _MAX_AI_SUSPECT_RETRIES:
                    await _reject_and_save(
                        message, state, {**data, "ai_suspect_flagged_keys": flagged_keys},
                        answers, ai_scores, t("ai_suspect_reject", lang), "rejected_ai_generated",
                    )
                    return
                await state.update_data(
                    ai_suspect_retry_count=ai_suspect_count, awaiting_followup_for=idx,
                    ai_suspect_flagged_keys=flagged_keys,
                )
                await message.answer(t("ai_suspect_retry", lang, question_text=q["text"]))
                return

        await state.update_data(
            answers=answers, ai_scores=ai_scores, question_index=idx + 1,
            awaiting_followup_for=None, irrelevant_retry_count=0, ai_suspect_retry_count=0,
        )
        await ask_current_question(message, state)
        return

    # --- Hard filter: salbiy javob bo'lsa, darhol xushmuomalalik bilan rad etamiz ---
    if q.get("hard_filter") and is_negative_answer(answer_text):
        answers = data.get("answers", {})
        answers[q["key"]] = answer_text
        await _reject_and_save(
            message, state, data, answers, data.get("ai_scores", {}),
            data["vacancy_reject_message"], "rejected_hard_filter",
        )
        return

    answers = data.get("answers", {})
    answers[q["key"]] = answer_text
    ai_scores = data.get("ai_scores", {})

    # --- Har bir javob uchun: mavzuga/kasbga aloqadormi degan tekshiruv ---
    relevant = True
    result = None
    if q.get("ai_score"):
        result = await score_answer(q["text"], answer_text)
        if result is not None:
            ai_scores[q["key"]] = result
            relevant = result.get("relevant", True)
    elif not q.get("ai_score") and len(answer_text) > _SHORT_ANSWER_SKIP_CHARS:
        # Oddiy faktik savollarda (masalan "qaysi platforma/dastur ishlatasiz")
        # juda qisqa javoblar ("Instagram", "Figma" kabi) deyarli doim to'g'ri
        # bo'ladi — AI bunday qisqa matnlarni ba'zan noto'g'ri "aloqasiz" deb
        # belgilashi mumkin, shuning uchun tekshiruvni faqat uzunroq javoblarga
        # qo'llaymiz (noto'g'ri rad etish xavfini kamaytirish uchun).
        checked = await check_relevance(q["text"], answer_text)
        if checked is not None:
            relevant = checked

    if not relevant:
        # AI xato qilishi mumkinligi uchun, birinchi marta darhol rad etmaymiz —
        # SHU SAVOLNING O'ZIDA qolib, qayta javob berish imkonini beramiz
        # (boshqa javoblar, fayl va h.k. saqlanib qoladi, jarayon qaytadan
        # boshlanmaydi).
        retry_count = data.get("irrelevant_retry_count", 0) + 1
        if retry_count > _MAX_IRRELEVANT_RETRIES:
            await _reject_and_save(
                message, state, data, answers, ai_scores,
                t("irrelevant_reject", lang), "rejected_irrelevant",
            )
            return

        await state.update_data(irrelevant_retry_count=retry_count)
        await message.answer(t("irrelevant_retry", lang, question_text=q["text"]))
        return

    # --- Javob "AI orqali yozilgan" deb gumon qilinsa — qabul qilmaymiz, nomzoddan
    # o'z so'zi bilan qayta javob berishni so'raymiz (cheklangan urinish bilan). ---
    if result is not None and "ai_yozgan" in result.get("red_flags", []):
        flagged_keys = data.get("ai_suspect_flagged_keys", [])
        if q["key"] not in flagged_keys:
            flagged_keys.append(q["key"])

        ai_suspect_count = data.get("ai_suspect_retry_count", 0) + 1
        if ai_suspect_count > _MAX_AI_SUSPECT_RETRIES:
            await _reject_and_save(
                message, state, {**data, "ai_suspect_flagged_keys": flagged_keys},
                answers, ai_scores, t("ai_suspect_reject", lang), "rejected_ai_generated",
            )
            return

        await state.update_data(
            ai_suspect_retry_count=ai_suspect_count, ai_suspect_flagged_keys=flagged_keys,
        )
        await message.answer(t("ai_suspect_retry", lang, question_text=q["text"]))
        return

    # --- Javob mavzuga oid, lekin sifati past/abstrakt bo'lsa — bitta marta
    # aniqlashtiruvchi savol beramiz (har bir savol uchun faqat bir marta). ---
    needs_followup = result is not None and (
        result["score"] < _FOLLOWUP_SCORE_THRESHOLD or "abstrakt_javob" in result.get("red_flags", [])
    )
    already_followed_up = idx in data.get("followup_asked_indices", [])

    if needs_followup and not already_followed_up:
        followup_indices = data.get("followup_asked_indices", [])
        followup_indices.append(idx)
        await state.update_data(
            answers=answers, ai_scores=ai_scores,
            followup_asked_indices=followup_indices, awaiting_followup_for=idx,
        )
        builder = InlineKeyboardBuilder()
        builder.button(text=t("followup_skip_button", lang), callback_data="followup:skip")
        await message.answer(t("followup_prompt", lang), reply_markup=builder.as_markup())
        return

    await state.update_data(
        answers=answers, ai_scores=ai_scores, question_index=idx + 1,
        irrelevant_retry_count=0, ai_suspect_retry_count=0,
    )
    await ask_current_question(message, state)


@router.callback_query(ApplyForm.answering_questions, F.data == "followup:skip")
async def skip_followup(callback: CallbackQuery, state: FSMContext):
    """Nomzod aniqlashtiruvchi savolni o'tkazib, dastlabki javobi bilan davom etadi."""
    data = await state.get_data()
    idx = data.get("awaiting_followup_for")
    if idx is None:
        await callback.answer()
        return

    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await state.update_data(
        question_index=idx + 1, awaiting_followup_for=None,
        irrelevant_retry_count=0, ai_suspect_retry_count=0,
    )
    await ask_current_question(callback.message, state)


@router.message(ApplyForm.answering_questions)
async def handle_wrong_answer_type(message: Message, state: FSMContext):
    """Savol kutilayotganda matn/ovozdan boshqa narsa (rasm, stiker va h.k.) yuborilsa."""
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    idx = data["question_index"]
    questions = data["vacancy_questions"]

    if questions[idx].get("voice"):
        await message.answer(t("voice_required", lang))
        return

    await message.answer(t("wrong_answer_type", lang))


async def finish_questions(message: Message, state: FSMContext):
    """Barcha savollar tugagach chaqiriladi — rezyume/portfolio so'raladi (ixtiyoriy)."""
    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)

    # Agar rezyume savollardan OLDIN allaqachon olingan bo'lsa, qayta so'ramaymiz.
    if data.get("resume_file_id") or data.get("video_file_id"):
        from handlers.contact import ask_full_name

        await ask_full_name(message, state)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text=t("skip_button", lang), callback_data="skip_resume")

    await message.answer(t("finish_resume_prompt", lang), reply_markup=builder.as_markup())
    await state.set_state(ApplyForm.waiting_file)


_TRIAL_APPLICATION_LIMIT = 5


def _tariff_choice_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from services.plans import PLAN_ORDER, PLANS

    builder = InlineKeyboardBuilder()
    for key in PLAN_ORDER:
        plan = PLANS[key]
        builder.button(text=f"{plan['name']} — {plan['price']:,} so'm".replace(",", " "),
                        callback_data=f"billing:view:{key}")
    builder.adjust(1)
    return builder.as_markup()


async def _send_tariff_choices(tenant: dict, reason: str):
    """Sinov yoki tarif muddati/limiti tugaganda, mijozning O'Z Admin
    panel-boti orqali 3 ta tarifni tavsiflari bilan yuboradi."""
    from aiogram import Bot
    from services.plans import PLAN_ORDER, PLANS, format_plan_line

    if not tenant["admin_user_ids"] or not tenant.get("admin_bot_token"):
        return

    header = (
        "🎁 Bepul sinovingiz tugadi!" if reason == "trial"
        else "⏳ Joriy tarifingizning muddati yoki limiti tugadi!"
    )
    lines = [header, "", "Davom ettirish uchun mos tarifni tanlang:", ""]
    for key in PLAN_ORDER:
        lines.append(format_plan_line(PLANS[key]))
        lines.append("")

    bot = Bot(token=tenant["admin_bot_token"])
    try:
        await bot.send_message(
            chat_id=tenant["admin_user_ids"][0],
            text="\n".join(lines),
            reply_markup=_tariff_choice_keyboard(),
        )
    except Exception:
        logger.exception("Mijozga tarif tanlovini yuborib bo'lmadi (tenant_id=%s).", tenant["id"])
    finally:
        await bot.session.close()


async def _maybe_expire_trial(tenant_id: int):
    """Sinov (5 ta ariza) yoki joriy tarif (ariza soni/kun) tugaganda —
    davrni yopadi ('trial_expired') va 3 ta tarifni tanlash uchun yuboradi."""
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        return

    if tenant["status"] == "trial":
        count = tenant.get("applications_ever_count", 0)
        if count < _TRIAL_APPLICATION_LIMIT:
            return
        await database.update_tenant_status(tenant_id, "trial_expired")
        logger.info("Mijoz (id=%s) sinov limitiga yetdi (%s ta ariza).", tenant_id, count)
        await _send_tariff_choices(tenant, reason="trial")
        return

    if tenant["status"] == "active" and tenant.get("plan"):
        from datetime import datetime, timezone

        limit = tenant.get("plan_applications_limit")
        expires_at = tenant.get("plan_expires_at")
        used = tenant.get("applications_used_in_period", 0)

        expired_by_count = limit is not None and used >= limit
        expired_by_date = bool(expires_at) and datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at)
        if not (expired_by_count or expired_by_date):
            return

        await database.update_tenant_status(tenant_id, "trial_expired")
        logger.info("Mijoz (id=%s) tarif limitiga yetdi (ariza=%s/%s, muddat=%s).",
                    tenant_id, used, limit, expires_at)
        await _send_tariff_choices(tenant, reason="plan")


async def complete_application(message: Message, state: FSMContext):
    """handlers/contact.py orqali ism-familiya va telefon yig'ilgach chaqiriladi."""
    from handlers.admin import notify_admins
    from handlers.sell import maybe_send_sell_pitch

    data = await state.get_data()
    lang = data.get("lang", DEFAULT_LANG)
    tenant_id = data["tenant_id"]

    app_id = await database.save_application(
        tenant_id=tenant_id,
        user_id=message.from_user.id,
        username=message.from_user.username or "",
        full_name=data.get("candidate_full_name") or message.from_user.full_name,
        phone_number=data.get("candidate_phone", ""),
        vacancy_key=data["vacancy_key"],
        vacancy_title=data["vacancy_title"],
        answers=data.get("answers", {}),
        ai_scores=data.get("ai_scores", {}),
        resume_file_id=data.get("resume_file_id"),
        video_file_id=data.get("video_file_id"),
        status="pending",
        lang=lang,
        ai_suspect_flags=data.get("ai_suspect_flagged_keys", []),
        voice_answers=data.get("voice_answers", {}),
    )

    await message.answer(t("application_submitted", lang))
    await state.set_state(ApplyForm.finished)
    await state.clear()

    try:
        await notify_admins(tenant_id, app_id, message.bot)
    except Exception:
        logger.exception("Adminlarga xabar yuborib bo'lmadi (app_id=%s).", app_id)

    # --- Sinov limiti: agar bu mijoz hali SINOV rejimida bo'lsa va limitga
    # yetgan bo'lsa, sinovni yopib, to'lov so'raymiz. ---
    try:
        await _maybe_expire_trial(tenant_id)
    except Exception:
        logger.exception("Sinov limitini tekshirishda xato (tenant_id=%s).", tenant_id)

    # --- Sell bosqichi: agar nomzod yuqori ball olsa, avtomatik taklif yuboriladi ---
    try:
        await maybe_send_sell_pitch(message, tenant_id, app_id, data.get("ai_scores", {}), lang)
    except Exception:
        logger.exception("Sell xabarini yuborib bo'lmadi (app_id=%s).", app_id)
