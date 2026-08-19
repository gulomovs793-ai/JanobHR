"""Janob HR Bot — savol-javob oqimi, hard-filter, mavzuga aloqadorlik va AI baholash."""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MAX_ANSWER_CHARS
from services import database
from services.ai_scoring import check_relevance, score_answer
from states import ApplyForm
from vacancies import is_negative_answer

logger = logging.getLogger("janob_hr_bot")

router = Router(name="questions")


async def ask_current_question(message: Message, state: FSMContext):
    data = await state.get_data()
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
    await message.answer(f"<b>Savol {idx + 1}/{total}</b>\n\n{questions[idx]['text']}")
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
    )
    await state.clear()


_IRRELEVANT_RETRY_TEXT = (
    "Kechirasiz, javobingiz savolga unchalik mos kelmadi. 🤔\n\n"
    "Iltimos, quyidagi savolga qayta, aniqroq javob bering:\n\n"
    "{question_text}"
)

_IRRELEVANT_REJECT_TEXT = (
    "Kechirasiz, bir necha marta savolga mos javob bera olmadingiz. ⚠️\n\n"
    "Iltimos, keyinroq /start orqali qaytadan urinib ko'ring va savollarga jiddiy, "
    "mavzuga oid javob bering."
)

# Oddiy faktik savollarda ("qaysi platforma/dastur ishlatasiz" kabi) bundan qisqa
# javoblar AI orqali tekshirilmaydi — bir so'zlik to'g'ri javoblarni ("Instagram",
# "Figma") noto'g'ri "aloqasiz" deb belgilash xavfini kamaytirish uchun.
_SHORT_ANSWER_SKIP_CHARS = 20

# AI ba'zan to'g'ri javoblarni ham noto'g'ri "aloqasiz" deb belgilashi mumkin —
# shuning uchun bitta xato tufayli butun arizani yo'qotmaslik uchun, nomzodga
# SHU SAVOLNI qayta javob berishga necha marta imkoniyat berilishi (ketma-ket
# necha marta "aloqasiz" chiqsa, arizani chindan rad etamiz).
_MAX_IRRELEVANT_RETRIES = 2

# Javob mavzuga oid, lekin sifati past yoki abstrakt bo'lsa (aniq raqam/misolsiz),
# bot BITTA marta (har bir savol uchun ko'pi bilan bir marta) aniqlashtiruvchi
# savol beradi — bu nomzodga fikrini kengaytirish imkonini beradi, adminga esa
# to'liqroq ma'lumot bilan yetib boradi.
_FOLLOWUP_SCORE_THRESHOLD = 50

_FOLLOWUP_PROMPT_TEXT = (
    "Javobingiz biroz umumiy chiqdi. 🤔 Iltimos, aniqroq misol, raqam yoki qadam bilan "
    "kengaytirib qayta yozing.\n\nAgar shu javobingiz bilan davom etmoqchi bo'lsangiz, "
    "pastdagi tugmani bosing."
)


@router.message(ApplyForm.answering_questions, F.text)
async def handle_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["question_index"]
    questions = data["vacancy_questions"]
    q = questions[idx]
    answer_text = message.text.strip()

    if not answer_text:
        await message.answer("Iltimos, savolga matn ko'rinishida javob yozing.")
        return

    # --- Uzunlik chegarasi: juda uzun javoblar o'qishni va AI tahlilini qiyinlashtiradi ---
    if len(answer_text) > MAX_ANSWER_CHARS:
        await message.answer(
            f"Javobingiz juda uzun ({len(answer_text)} belgi). Iltimos, fikringizni "
            f"qisqaroq — taxminan {MAX_ANSWER_CHARS} belgigacha — qilib qayta yozing. ✍️"
        )
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

        await state.update_data(
            answers=answers, ai_scores=ai_scores, question_index=idx + 1,
            awaiting_followup_for=None, irrelevant_retry_count=0,
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
    elif len(answer_text) > _SHORT_ANSWER_SKIP_CHARS:
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
                _IRRELEVANT_REJECT_TEXT, "rejected_irrelevant",
            )
            return

        await state.update_data(irrelevant_retry_count=retry_count)
        await message.answer(_IRRELEVANT_RETRY_TEXT.format(question_text=q["text"]))
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
        builder.button(text="✅ Shu javobim bilan davom etaman", callback_data="followup:skip")
        await message.answer(_FOLLOWUP_PROMPT_TEXT, reply_markup=builder.as_markup())
        return

    await state.update_data(
        answers=answers, ai_scores=ai_scores, question_index=idx + 1,
        irrelevant_retry_count=0,
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
        question_index=idx + 1, awaiting_followup_for=None, irrelevant_retry_count=0,
    )
    await ask_current_question(callback.message, state)


@router.message(ApplyForm.answering_questions)
async def handle_wrong_answer_type(message: Message):
    """Savol kutilayotganda matndan boshqa narsa (rasm, stiker va h.k.) yuborilsa."""
    await message.answer("Iltimos, javobingizni oddiy matn ko'rinishida yozing. ✍️")


async def finish_questions(message: Message, state: FSMContext):
    """Barcha savollar tugagach chaqiriladi — rezyume/portfolio so'raladi (ixtiyoriy)."""
    data = await state.get_data()

    # Agar rezyume savollardan OLDIN allaqachon olingan bo'lsa, qayta so'ramaymiz.
    if data.get("resume_file_id") or data.get("video_file_id"):
        from handlers.contact import ask_full_name

        await ask_full_name(message, state)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ O'tkazib yuborish", callback_data="skip_resume")

    await message.answer(
        "Deyarli tugadi! Agar mavjud bo'lsa, rezyume (PDF fayl), video-vizitka yoki "
        "portfolio havolangizni (link) yuboring — bu ixtiyoriy, xohlasangiz o'tkazib "
        "yuborishingiz mumkin.",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(ApplyForm.waiting_file)


async def complete_application(message: Message, state: FSMContext):
    """handlers/contact.py orqali ism-familiya va telefon yig'ilgach chaqiriladi."""
    from handlers.admin import notify_admins
    from handlers.sell import maybe_send_sell_pitch

    data = await state.get_data()

    app_id = await database.save_application(
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
    )

    await message.answer("✅ Anketangiz qabul qilindi! Tez orada siz bilan bog'lanamiz. Rahmat!")
    await state.set_state(ApplyForm.finished)
    await state.clear()

    try:
        await notify_admins(app_id)
    except Exception:
        logger.exception("Adminlarga xabar yuborib bo'lmadi (app_id=%s).", app_id)

    # --- Sell bosqichi: agar nomzod yuqori ball olsa, avtomatik taklif yuboriladi ---
    try:
        await maybe_send_sell_pitch(message, app_id, data.get("ai_scores", {}))
    except Exception:
        logger.exception("Sell xabarini yuborib bo'lmadi (app_id=%s).", app_id)
