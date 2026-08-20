"""
Admin bot — vakansiya yaratish va mavjudini tahrirlash (savollarni AI orqali
generatsiya qilish yoki qo'lda kiritish). Ikkala oqim (yangi yaratish va
mavjudini yangilash) bir xil bosqichlarni ishlatadi — FSM ma'lumotidagi
`editing_vacancy_key` maydoni orqali farqlanadi (mavjud bo'lsa — tahrirlash,
bo'lmasa — yangi yaratish).
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin_bot.parsing import MANUAL_FORMAT_HELP, format_questions_preview, parse_manual_questions, to_manual_format
from admin_bot.states import AdminForm
from services import database
from services.ai_scoring import generate_questions

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_vacancy_edit")

_DEFAULT_REJECT_MESSAGE = (
    "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
    "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
)


# ============================= 1) YANGI VAKANSIYA BOSHLASH =============================

@router.callback_query(F.data == "menu:new")
async def start_new_vacancy(callback: CallbackQuery, state: FSMContext):
    await state.clear()  # editing_vacancy_key bo'lmasligi kerak — bu YANGI yaratish
    await callback.message.edit_text(
        "➕ <b>Yangi vakansiya</b>\n\nLavozim nomini yozing (masalan: \"Quruvchi\", \"Buxgalter\", \"Haydovchi\")."
    )
    await state.set_state(AdminForm.creating_title)
    await callback.answer()


@router.message(AdminForm.creating_title, F.text)
async def receive_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) < 2:
        await message.answer("Iltimos, lavozim nomini yozing.")
        return

    await state.update_data(vacancy_title=title)
    await message.answer(
        "Endi shu lavozim haqida qisqacha yozing: qanday vazifalar, qanday natija kutiladi, "
        "qanday ko'nikmalar kerak? (Bu AI'ga to'g'ri savollar tuzishga yordam beradi.)\n\n"
        "Agar batafsil yozishni istamasangiz, shunchaki bir-ikki gap yozsangiz ham bo'ladi."
    )
    await state.set_state(AdminForm.creating_description)


# ============================= 2) MAVJUDNI AI BILAN YANGILASH =============================

@router.callback_query(F.data.startswith("vacregen:"))
async def start_regenerate(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    await state.update_data(editing_vacancy_key=key, vacancy_title=vacancy["title"])
    await callback.message.edit_text(
        f"🔄 <b>{vacancy['title']}</b> uchun savollarni AI bilan qayta tuzamiz.\n\n"
        "Lavozim haqida qisqacha yozing (vazifalar, kutilgan natija, kerakli ko'nikmalar):"
    )
    await state.set_state(AdminForm.editing_description_for_regen)
    await callback.answer()


@router.message(AdminForm.editing_description_for_regen, F.text)
async def receive_regen_description(message: Message, state: FSMContext):
    await state.update_data(vacancy_description=message.text.strip())
    await _generate_and_show(message, state)


@router.message(AdminForm.creating_description, F.text)
async def receive_description(message: Message, state: FSMContext):
    await state.update_data(vacancy_description=message.text.strip())
    await _generate_and_show(message, state)


async def _generate_and_show(message: Message, state: FSMContext):
    data = await state.get_data()
    wait_msg = await message.answer("🤖 AI savollarni tuzmoqda, bir necha soniya kuting...")

    questions = await generate_questions(data["vacancy_title"], data.get("vacancy_description", ""))

    if not questions:
        await wait_msg.edit_text(
            "⚠️ AI hozircha savol tuza olmadi (barcha provayderlar band yoki xato berdi). "
            "Savollarni qo'lda kiritamiz.\n\n" + MANUAL_FORMAT_HELP
        )
        await state.set_state(AdminForm.entering_manual_questions)
        return

    await state.update_data(pending_questions=questions)
    await wait_msg.edit_text(
        f"🤖 <b>AI taklif qilgan savollar</b> ({len(questions)} ta):\n\n"
        f"{format_questions_preview(questions)}\n\n"
        "🔒 — majburiy filtr savoli (salbiy javobda nomzod avtomatik rad etiladi).",
        reply_markup=_review_keyboard(),
    )
    await state.set_state(AdminForm.reviewing_ai_questions)


async def _show_review(message: Message, questions: list[dict]):
    await message.answer(
        f"<b>Savollar ro'yxati</b> ({len(questions)} ta):\n\n"
        f"{format_questions_preview(questions)}\n\n"
        "🔒 — majburiy filtr savoli (salbiy javobda nomzod avtomatik rad etiladi).",
        reply_markup=_review_keyboard(),
    )


def _review_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Saqlash", callback_data="aiq:save")
    builder.button(text="✏️ Bitta savolni tahrirlash", callback_data="aiq:editlist")
    builder.button(text="🔄 Qayta generatsiya qilish", callback_data="aiq:regen")
    builder.button(text="✍️ O'zim yozaman", callback_data="aiq:manual")
    builder.button(text="❌ Bekor qilish", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


# ============================= 3) AI TAKLIFINI KO'RIB CHIQISH =============================

@router.callback_query(AdminForm.reviewing_ai_questions, F.data == "aiq:regen")
async def regenerate_questions(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Qayta generatsiya qilinmoqda...")
    await _generate_and_show(callback.message, state)


@router.callback_query(AdminForm.reviewing_ai_questions, F.data == "aiq:manual")
async def switch_to_manual(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    prefill = to_manual_format(data.get("pending_questions", []))
    await callback.message.edit_text(
        "✍️ Savollarni o'zingiz kiriting.\n\n"
        + MANUAL_FORMAT_HELP
        + "\n\n<b>AI taklifini boshlang'ich nuqta sifatida ishlatishingiz mumkin "
        "(nusxalab, tahrirlab qayta yuboring):</b>\n\n<code>"
        + prefill.replace("<", "&lt;").replace(">", "&gt;")
        + "</code>"
    )
    await state.set_state(AdminForm.entering_manual_questions)
    await callback.answer()


@router.callback_query(AdminForm.reviewing_ai_questions, F.data == "aiq:save")
async def accept_ai_questions(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(final_questions=data.get("pending_questions", []))
    await callback.answer("Saqlanmoqda...")
    await _finalize_vacancy(callback.message, state)


@router.callback_query(AdminForm.reviewing_ai_questions, F.data == "aiq:editlist")
async def show_pending_question_picker(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions = data.get("pending_questions", [])

    builder = InlineKeyboardBuilder()
    for i, q in enumerate(questions):
        label = q["text"] if len(q["text"]) <= 45 else q["text"][:45] + "…"
        builder.button(text=f"{i + 1}. {label}", callback_data=f"aiq:editq:{i}")
    builder.button(text="⬅️ Orqaga", callback_data="aiq:back")
    builder.adjust(1)

    await callback.message.edit_text(
        "✏️ Qaysi savolni tahrirlaysiz?", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(AdminForm.reviewing_ai_questions, F.data == "aiq:back")
async def back_to_review_from_picker(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    questions = data.get("pending_questions", [])
    await callback.message.edit_text(
        f"<b>Savollar ro'yxati</b> ({len(questions)} ta):\n\n"
        f"{format_questions_preview(questions)}\n\n"
        "🔒 — majburiy filtr savoli (salbiy javobda nomzod avtomatik rad etiladi).",
        reply_markup=_review_keyboard(),
    )
    await callback.answer()


@router.callback_query(AdminForm.reviewing_ai_questions, F.data.startswith("aiq:editq:"))
async def start_edit_pending_question(callback: CallbackQuery, state: FSMContext):
    idx = int(callback.data.split(":")[2])
    data = await state.get_data()
    questions = data.get("pending_questions", [])
    if idx >= len(questions):
        await callback.answer("Bu savol topilmadi.", show_alert=True)
        return

    await state.update_data(editing_pending_index=idx)
    await callback.message.edit_text(
        f"✏️ <b>{idx + 1}-savol</b>\n\nJoriy matn:\n<i>{questions[idx]['text']}</i>\n\n"
        "Yangi matnni yozing. Ixtiyoriy ravishda oxiriga belgi qo'shishingiz mumkin:\n"
        "  <code>| filter</code> — majburiy filtr savoli\n"
        "  <code>| voice</code> — ovozli xabar orqali javob va AI tahlil\n"
        "  <code>| score</code> — AI chuqur tahlil qiladi\n\n"
        "Hech qanday belgi qo'shmasangiz, oddiy savol bo'lib qoladi."
    )
    await state.set_state(AdminForm.editing_pending_question)
    await callback.answer()


@router.message(AdminForm.editing_pending_question, F.text)
async def receive_pending_question_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    idx = data["editing_pending_index"]
    questions = list(data.get("pending_questions", []))

    parsed = parse_manual_questions(message.text)
    if not parsed:
        await message.answer("Savol matni bo'sh bo'lmasligi kerak. Qaytadan yozing.")
        return

    new_question = parsed[0]
    if idx < len(questions):
        new_question["key"] = questions[idx].get("key", new_question["key"])
        questions[idx] = new_question

    await state.update_data(pending_questions=questions)
    await state.set_state(AdminForm.reviewing_ai_questions)
    await message.answer(f"✅ {idx + 1}-savol yangilandi.")
    await _show_review(message, questions)


# ============================= 4) QO'LDA KIRITISH =============================

@router.message(AdminForm.entering_manual_questions, F.text)
async def receive_manual_questions(message: Message, state: FSMContext):
    questions = parse_manual_questions(message.text)
    if not questions:
        await message.answer("Hech bo'lmasa bitta savol kiriting. Qaytadan urinib ko'ring.")
        return

    await state.update_data(final_questions=questions)
    await _finalize_vacancy(message, state)


# ============================= 5) YAKUNLASH (saqlash) =============================

async def _finalize_vacancy(message: Message, state: FSMContext):
    data = await state.get_data()
    title = data["vacancy_title"]
    questions = data.get("final_questions", [])
    editing_key = data.get("editing_vacancy_key")

    if editing_key:
        await database.update_vacancy(editing_key, title=title, questions=questions)
        result_text = f"✅ <b>{title}</b> vakansiyasi yangilandi ({len(questions)} ta savol)."
    else:
        base_key = database.make_vacancy_key(title)
        key = base_key
        n = 2
        while await database.get_vacancy(key):
            key = f"{base_key}_{n}"
            n += 1

        # Rezyume/portfolio so'rash endi barcha vakansiyalar uchun universal va
        # ixtiyoriy (handlers/questions.py'da), shuning uchun bu yerda alohida
        # so'ralmaydi — standart True qiymati saqlanadi, lekin amalda ishlatilmaydi.
        await database.create_vacancy(
            key=key, title=title, reject_message=_DEFAULT_REJECT_MESSAGE,
            questions=questions, resume_required=True,
        )
        result_text = (
            f"✅ Yangi vakansiya yaratildi: <b>{title}</b> ({len(questions)} ta savol).\n\n"
            "Nomzodlar botiga /start yuborib, darhol ko'rishlari mumkin."
        )

    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Vakansiyalar ro'yxati", callback_data="menu:vacancies")
    builder.button(text="🏠 Bosh menyu", callback_data="menu:main")
    builder.adjust(1)
    await message.answer(result_text, reply_markup=builder.as_markup())


# ============================= 6) TO'G'RIDAN-TO'G'RI QO'LDA TAHRIRLASH =============================

@router.callback_query(F.data.startswith("vacmanual:"))
async def start_manual_edit(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    await state.update_data(editing_vacancy_key=key, vacancy_title=vacancy["title"])
    prefill = to_manual_format(vacancy["questions"])
    await callback.message.edit_text(
        f"✍️ <b>{vacancy['title']}</b> — savollarni tahrirlang.\n\n"
        + MANUAL_FORMAT_HELP
        + "\n\n<b>Hozirgi savollar (nusxalab, tahrirlab qayta yuboring):</b>\n\n<code>"
        + prefill.replace("<", "&lt;").replace(">", "&gt;")
        + "</code>"
    )
    await state.set_state(AdminForm.entering_manual_questions)
    await callback.answer()


# ============================= 7) BITTA SAVOLNI ALOHIDA TAHRIRLASH =============================

@router.callback_query(F.data.startswith("vaceditlist:"))
async def show_question_picker(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    for i, q in enumerate(vacancy["questions"]):
        label = q["text"] if len(q["text"]) <= 45 else q["text"][:45] + "…"
        builder.button(text=f"{i + 1}. {label}", callback_data=f"vaceditq:{key}:{i}")
    builder.button(text="⬅️ Orqaga", callback_data=f"vac:{key}")
    builder.adjust(1)

    await callback.message.edit_text(
        f"✏️ <b>{vacancy['title']}</b> — qaysi savolni tahrirlaysiz?",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("vaceditq:"))
async def start_edit_single_question(callback: CallbackQuery, state: FSMContext):
    _, key, idx_str = callback.data.split(":")
    idx = int(idx_str)
    vacancy = await database.get_vacancy(key)
    if not vacancy or idx >= len(vacancy["questions"]):
        await callback.answer("Bu savol topilmadi.", show_alert=True)
        return

    current = vacancy["questions"][idx]
    await state.update_data(editing_vacancy_key=key, editing_question_index=idx)
    await callback.message.edit_text(
        f"✏️ <b>{idx + 1}-savol</b>\n\nJoriy matn:\n<i>{current['text']}</i>\n\n"
        "Yangi matnni yozing. Ixtiyoriy ravishda oxiriga belgi qo'shishingiz mumkin:\n"
        "  <code>| filter</code> — majburiy filtr savoli\n"
        "  <code>| voice</code> — ovozli xabar orqali javob va AI tahlil\n"
        "  <code>| score</code> — AI chuqur tahlil qiladi\n\n"
        "Hech qanday belgi qo'shmasangiz, oddiy savol bo'lib qoladi."
    )
    await state.set_state(AdminForm.editing_single_question)
    await callback.answer()


@router.message(AdminForm.editing_single_question, F.text)
async def receive_single_question_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    key = data["editing_vacancy_key"]
    idx = data["editing_question_index"]

    parsed = parse_manual_questions(message.text)
    if not parsed:
        await message.answer("Savol matni bo'sh bo'lmasligi kerak. Qaytadan yozing.")
        return

    vacancy = await database.get_vacancy(key)
    if not vacancy or idx >= len(vacancy["questions"]):
        await message.answer("Bu vakansiya yoki savol endi topilmadi.")
        await state.clear()
        return

    new_question = parsed[0]
    new_question["key"] = vacancy["questions"][idx].get("key", new_question["key"])
    updated_questions = list(vacancy["questions"])
    updated_questions[idx] = new_question

    await database.update_vacancy(key, questions=updated_questions)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Vakansiyaga qaytish", callback_data=f"vac:{key}")
    await message.answer(f"✅ {idx + 1}-savol yangilandi.", reply_markup=builder.as_markup())
