"""
Janob HR Bot — vakansiya tanlangandan so'ng, savollardan OLDIN ixtiyoriy
ravishda rezyume (PDF) so'raladi. Agar nomzod PDF yuborsa, AI undan matn
chiqarib, oddiy FAKTIK savollarni (masalan "qaysi dastur ishlatasiz") avtomatik
to'ldiradi — shunday savollar keyin qayta so'ralmaydi.

MUHIM: Scorecard/Behavioral (ai_score bilan belgilangan) va hard_filter
savollar rezyumedan HECH QACHON to'ldirilmaydi — ular har doim nomzodning
o'zidan so'raladi, chunki aynan shu savollar orqali "faqat CV'da yaxshi
ko'rinadigan" nomzodlar chinakam tekshiriladi.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.ai_scoring import extract_resume_data
from services.pdf_reader import extract_pdf_text
from states import ApplyForm

logger = logging.getLogger("janob_hr_bot")

router = Router(name="resume_upfront")

_MIN_RESUME_TEXT_LEN = 50


async def ask_resume_upfront(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ O'tkazib yuborish", callback_data="skip_resume_upfront")
    await message.answer(
        "Agar tayyor rezyumeingiz (PDF) bo'lsa, avval shuni yuboring — men undan "
        "ba'zi ma'lumotlarni o'qib, sizga bir nechta savolni qayta berishning hojatini "
        "yo'q qilaman. 📄\n\nBo'lmasa, bemalol o'tkazib yuborishingiz mumkin.",
        reply_markup=builder.as_markup(),
    )
    await state.set_state(ApplyForm.waiting_resume_upfront)


async def _proceed_to_questions(message: Message, state: FSMContext):
    from handlers.questions import ask_current_question

    await ask_current_question(message, state)


@router.callback_query(ApplyForm.waiting_resume_upfront, F.data == "skip_resume_upfront")
async def skip_resume(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _proceed_to_questions(callback.message, state)


@router.message(ApplyForm.waiting_resume_upfront, F.document)
async def handle_resume_pdf(message: Message, state: FSMContext):
    is_pdf = (message.document.mime_type == "application/pdf") or (
        message.document.file_name or ""
    ).lower().endswith(".pdf")

    if not is_pdf:
        # PDF bo'lmasa (masalan rasm yoki boshqa fayl), shunchaki oddiy fayl
        # sifatida saqlaymiz — keyinroq savollardan keyin ham so'raladi, hech
        # narsa yo'qolmaydi.
        await state.update_data(resume_file_id=message.document.file_id)
        await message.answer("Fayl saqlandi. Endi savollarga o'tamiz.")
        await _proceed_to_questions(message, state)
        return

    wait_msg = await message.answer("📄 Rezyumeni o'qimoqdaman...")

    try:
        buffer = await message.bot.download(message.document)
        pdf_text = extract_pdf_text(buffer.read())
    except Exception:
        logger.exception("Rezyume PDF'ni yuklab bo'lmadi.")
        pdf_text = ""

    await state.update_data(resume_file_id=message.document.file_id)

    if len(pdf_text) < _MIN_RESUME_TEXT_LEN:
        # Skanerlangan/matnsiz PDF bo'lishi mumkin — baribir faylni saqlab qoldik,
        # shunchaki avtomatik to'ldirish ishlamaydi.
        await wait_msg.edit_text(
            "Faylni saqladim, lekin undan matn o'qib bo'lmadi (skanerlangan rasm "
            "bo'lishi mumkin). Hammasi joyida — savollarni odatdagidek davom ettiramiz."
        )
        await _proceed_to_questions(message, state)
        return

    data = await state.get_data()
    questions = data["vacancy_questions"]
    # Faqat ODDIY FAKTIK savollar (ai_score va hard_filter BELGILANMAGAN)
    # rezyumedan to'ldirilishi mumkin.
    eligible = [q for q in questions if not q.get("ai_score") and not q.get("hard_filter")]

    extracted = await extract_resume_data(pdf_text, eligible) if eligible else None

    if not extracted:
        await wait_msg.edit_text(
            "Faylni saqladim, lekin undan avtomatik to'ldirish uchun yetarli ma'lumot "
            "topa olmadim. Savollarni odatdagidek davom ettiramiz."
        )
        await _proceed_to_questions(message, state)
        return

    answers = data.get("answers", {})
    prefilled_texts = []
    key_by_text = {q["key"]: q["text"] for q in eligible}
    for key, value in extracted["answers"].items():
        answers[key] = f"{value} (rezyumedan)"
        prefilled_texts.append(key_by_text.get(key, key))

    if extracted.get("summary"):
        answers["_resume_summary"] = f"📄 Rezyume xulosasi: {extracted['summary']}"

    await state.update_data(
        answers=answers,
        prefilled_from_resume=list(extracted["answers"].keys()),
    )

    if prefilled_texts:
        skipped_list = "\n".join(f"✓ {t}" for t in prefilled_texts)
        await wait_msg.edit_text(
            f"✅ Rezyumeni o'qib chiqdim!\n\n"
            f"Quyidagi savollarni rezyumedan javob sifatida oldim, ularni qayta "
            f"so'ramayman:\n{skipped_list}\n\n"
            "Qolgan savollarni davom ettiramiz."
        )
    else:
        await wait_msg.edit_text("✅ Rezyumeni o'qib chiqdim. Savollarni davom ettiramiz.")

    await _proceed_to_questions(message, state)


@router.message(ApplyForm.waiting_resume_upfront, F.video)
async def handle_video_upfront(message: Message, state: FSMContext):
    await state.update_data(video_file_id=message.video.file_id)
    await message.answer("Video saqlandi. Endi savollarga o'tamiz.")
    await _proceed_to_questions(message, state)


@router.message(ApplyForm.waiting_resume_upfront, F.text)
async def handle_text_upfront(message: Message, state: FSMContext):
    text = message.text.strip()
    if text:
        data = await state.get_data()
        answers = data.get("answers", {})
        answers["portfolio_link"] = text
        await state.update_data(answers=answers)
    await message.answer("Qabul qilindi. Endi savollarga o'tamiz.")
    await _proceed_to_questions(message, state)
