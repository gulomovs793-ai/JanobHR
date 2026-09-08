"""
Admin bot — vakansiya yaratish va mavjudini tahrirlash (savollarni AI orqali
generatsiya qilish yoki qo'lda kiritish). Ikkala oqim (yangi yaratish va
mavjudini yangilash) bir xil bosqichlarni ishlatadi — FSM ma'lumotidagi
`editing_vacancy_key` maydoni orqali farqlanadi (mavjud bo'lsa — tahrirlash,
bo'lmasa — yangi yaratish).
"""

import logging
from html import escape
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin_bot.parsing import (
    parse_manual_questions,
)
from admin_bot.states import AdminForm
from services import database
from services.ai_scoring import generate_questions

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_vacancy_edit")


def format_questions_preview(questions):
    lines = []
    for i, q in enumerate(questions[:12], 1):
        kind = "🔒" if q.get("hard_filter") else "🎙" if q.get("voice") else "🤖" if q.get("ai_score") else "💬"
        text = str(q["text"]).strip()
        lines.append(f"{i}. {escape(text)} {kind}")
    if len(questions) > 12:
        lines.append(f"Yana {len(questions) - 12} ta savol bor.")
    return "\n".join(lines)

_DEFAULT_REJECT_MESSAGE = (
    "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
    "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
)


# ============================= 1) YANGI VAKANSIYA BOSHLASH =============================


@router.callback_query(F.data == "menu:new")
async def start_new_vacancy(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    usage = await database.get_subscription_usage(tenant_id)
    if not usage["vacancies_available"]:
        await callback.message.edit_text(
            "🔒 <b>Vakansiya limiti tugagan</b>\n\nTarifni oshiring yoki mavjud faol vakansiyalardan birini vaqtincha yoping.",
            reply_markup=InlineKeyboardBuilder().button(
                text="💳 Tarifni yangilash", callback_data="menu:billing"
            ).button(text="⬅️ Bosh menyu", callback_data="menu:main").adjust(1).as_markup(),
        )
        await callback.answer()
        return
    await state.clear()  # editing_vacancy_key bo'lmasligi kerak — bu YANGI yaratish
    await callback.message.edit_text(
        '➕ <b>Yangi vakansiya</b>\n\nLavozim nomini yozing (masalan: "Quruvchi", "Buxgalter", "Haydovchi").'
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
async def start_regenerate(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
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
    wait_msg = await message.answer(
        "🤖 AI savollarni tuzmoqda, bir necha soniya kuting..."
    )

    questions = await generate_questions(
        data["vacancy_title"], data.get("vacancy_description", "")
    )

    if not questions:
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Qayta urinish", callback_data="vacgen:retry")
        builder.button(text="✍️ O'zim yozaman", callback_data="vacgen:manual")
        builder.adjust(1)
        await wait_msg.edit_text(
            "⚠️ AI hozircha savol tuza olmadi. Qayta urinib ko'rishingiz yoki "
            "savollarni o'zingiz yozishingiz mumkin:",
            reply_markup=builder.as_markup(),
        )
        return

    await state.update_data(pending_questions=questions)
    await wait_msg.edit_text(
        f"🤖 <b>AI taklif qilgan savollar</b> ({len(questions)} ta):\n\n"
        f"{format_questions_preview(questions)}\n\n"
        "🔒 — majburiy filtr savoli (salbiy javobda nomzod avtomatik rad etiladi).",
        reply_markup=_review_keyboard(),
    )
    await state.set_state(AdminForm.reviewing_ai_questions)


@router.callback_query(F.data == "vacgen:retry")
async def retry_generation(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Qayta urinilmoqda...")
    await _generate_and_show(callback.message, state)


@router.callback_query(F.data == "vacgen:manual")
async def switch_to_manual_after_failure(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("vacancy_title"):
        await callback.answer("Avval vakansiyani tanlang.", show_alert=True)
        return
    await _ask_manual_question(callback.message, state)
    await callback.answer()


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
    builder.button(text="➕ Savol qo'shish", callback_data="aiq:manual")
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
    await _ask_manual_question(callback.message, state)
    await callback.answer()


@router.callback_query(AdminForm.reviewing_ai_questions, F.data == "aiq:save")
async def accept_ai_questions(
    callback: CallbackQuery, state: FSMContext, tenant_id: int
):
    data = await state.get_data()
    if not data.get("pending_questions"):
        await callback.answer("Avval kamida bitta savol qo'shing.", show_alert=True)
        return
    await state.update_data(final_questions=data.get("pending_questions", []))
    await callback.answer("Saqlanmoqda...")
    await _finalize_vacancy(callback.message, state, tenant_id)


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


@router.callback_query(
    AdminForm.reviewing_ai_questions, F.data.startswith("aiq:editq:")
)
async def start_edit_pending_question(callback: CallbackQuery, state: FSMContext):
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[:2] != ["aiq", "editq"] or not parts[2].isdecimal():
        await callback.answer("Noto'g'ri savol so'rovi.", show_alert=True)
        return
    idx = int(parts[2])
    data = await state.get_data()
    questions = data.get("pending_questions", [])
    if idx >= len(questions):
        await callback.answer("Bu savol topilmadi.", show_alert=True)
        return

    await state.update_data(editing_pending_index=idx)
    await callback.message.edit_text(
        f"✏️ <b>{idx + 1}-savol</b>\n\n{escape(questions[idx]['text'])}\n\n"
        "Yangi savol matnini yozing. Keyin javob turini tugmadan tanlaysiz."
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

    if len(parsed) != 1 or len(parsed[0]["text"]) > 500:
        await message.answer("Bitta savol yozing (500 belgigacha).")
        return
    if idx >= len(questions):
        await message.answer("Savol topilmadi. Vakansiyani qayta oching.")
        return
    await state.update_data(manual_queue=parsed, manual_edit_index=idx)
    await _ask_question_type(message, state)


# ============================= 4) QO'LDA KIRITISH =============================



async def _ask_manual_question(message: Message, state: FSMContext):
    data = await state.get_data()
    builder = InlineKeyboardBuilder()
    if data.get("pending_questions"):
        builder.button(text="⬅️ Savollarga qaytish", callback_data="manual:review")
    builder.button(text="❌ Bekor qilish", callback_data="menu:main")
    await message.edit_text(
        "✍️ <b>Savolni yozing</b>\n\n"
        "Masalan: Qurilishda necha yil ishlagansiz?\n\n"
        "Keyin javob turini tugmadan tanlaysiz. "
        "Bir nechta savol bo'lsa, har birini yangi qatordan yozing.",
        reply_markup=builder.adjust(1).as_markup(),
    )
    await state.update_data(manual_queue=[], manual_edit_index=None)
    await state.set_state(AdminForm.entering_manual_questions)


async def _ask_question_type(message: Message, state: FSMContext):
    data = await state.get_data()
    question = data["manual_queue"][0]
    token = uuid4().hex[:8]
    builder = InlineKeyboardBuilder()
    for label, kind in [("💬 Oddiy yozma javob", "text"),
                        ("🤖 AI baholaydigan javob", "score"),
                        ("🎙 Ovozli javob", "voice"),
                        ("✅ Ha / Yo'q — saralash", "filter")]:
        builder.button(text=label, callback_data=f"manual:type:{token}:{kind}")
    builder.button(text="⬅️ Bekor qilish", callback_data="manual:review")
    await state.update_data(manual_type_token=token)
    await state.set_state(AdminForm.choosing_manual_type)
    await message.answer(
        f"<b>{escape(question['text'])}</b>\n\n"
        "Nomzod qanday javob bersin?\n"
        "🎙 Ovozli javobni o'zingiz tinglab baholaysiz.\n"
        "✅ Saralashda «Yo'q» javobi nomzodni avtomatik rad etadi.",
        reply_markup=builder.adjust(1).as_markup(),
    )


@router.callback_query(AdminForm.choosing_manual_type, F.data.startswith("manual:type:"))
async def choose_manual_type(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[2] != data.get("manual_type_token"):
        await callback.answer("Oxirgi savol tugmasidan foydalaning.")
        return
    kind = parts[3]
    if kind not in {"text", "score", "voice", "filter"}:
        await callback.answer()
        return
    queue = list(data.get("manual_queue", []))
    if not queue:
        await callback.answer()
        return
    item = queue.pop(0)
    questions = list(data.get("pending_questions", []))
    idx = data.get("manual_edit_index")
    question = {"key": "savol_" + uuid4().hex[:12], "text": item["text"]}
    flag = {"score": "ai_score", "voice": "voice", "filter": "hard_filter"}.get(kind)
    if flag:
        question[flag] = True
    if kind == "filter" and "ha/yo'q" not in question["text"].lower():
        question["text"] += " (Ha/Yo'q)"
    if idx is not None:
        if not 0 <= idx < len(questions):
            await callback.answer("Savol topilmadi.", show_alert=True)
            return
        question["key"] = questions[idx]["key"]
        questions[idx] = question
    else:
        questions.append(question)
    await state.update_data(pending_questions=questions, manual_queue=queue,
                            manual_edit_index=None, manual_type_token=None)
    await callback.answer("Qo'shildi")
    await callback.message.edit_reply_markup(reply_markup=None)
    if queue:
        await _ask_question_type(callback.message, state)
    else:
        await state.set_state(AdminForm.reviewing_ai_questions)
        await _show_review(callback.message, questions)


@router.callback_query(F.data == "manual:review")
async def manual_back_to_review(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.update_data(manual_queue=[], manual_edit_index=None, manual_type_token=None)
    if data.get("pending_questions"):
        await state.set_state(AdminForm.reviewing_ai_questions)
        await _show_review(callback.message, data["pending_questions"])
    else:
        await _ask_manual_question(callback.message, state)
    await callback.answer()


@router.message(AdminForm.choosing_manual_type)
async def remind_question_type(message: Message):
    await message.answer("Avval yuqoridagi tugmadan javob turini tanlang.")


@router.message(AdminForm.entering_manual_questions, F.text)
async def receive_manual_questions(message: Message, state: FSMContext, tenant_id: int):
    questions = parse_manual_questions(message.text)
    if not questions:
        await message.answer(
            "Hech bo'lmasa bitta savol kiriting. Qaytadan urinib ko'ring."
        )
        return

    data = await state.get_data()
    if len(questions) + len(data.get("pending_questions", [])) > 12 or any(len(q["text"]) > 500 for q in questions):
        await message.answer("Jami 12 tagacha savol qo'shing. Har bir savol 500 belgigacha bo'lsin.")
        return
    await state.update_data(manual_queue=questions, manual_edit_index=None)
    await _ask_question_type(message, state)


# ============================= 5) YAKUNLASH (saqlash) =============================


async def _finalize_vacancy(message: Message, state: FSMContext, tenant_id: int):
    data = await state.get_data()
    title = data["vacancy_title"]
    questions = data.get("final_questions", [])
    editing_key = data.get("editing_vacancy_key")

    if editing_key:
        await database.update_vacancy(
            tenant_id, editing_key, title=title, questions=questions
        )
        result_text = (
            f"✅ <b>{title}</b> vakansiyasi yangilandi ({len(questions)} ta savol)."
        )
    else:
        base_key = database.make_vacancy_key(title)
        key = base_key
        n = 2
        while await database.get_vacancy(tenant_id, key):
            key = f"{base_key}_{n}"
            n += 1

        # Rezyume/portfolio so'rash endi barcha vakansiyalar uchun universal va
        # ixtiyoriy (handlers/questions.py'da), shuning uchun bu yerda alohida
        # so'ralmaydi — standart True qiymati saqlanadi, lekin amalda ishlatilmaydi.
        try:
            await database.create_vacancy(
                tenant_id=tenant_id,
                key=key,
                title=title,
                reject_message=_DEFAULT_REJECT_MESSAGE,
                questions=questions,
                resume_required=True,
            )
        except database.VacancyLimitReached:
            await state.clear()
            builder = InlineKeyboardBuilder()
            builder.button(text="💳 Tarif va limitlar", callback_data="menu:billing")
            builder.button(text="📋 Vakansiyalar", callback_data="menu:vacancies")
            builder.adjust(1)
            await message.answer(
                "🔒 Bu orada faol vakansiya limiti band bo'ldi. Boshqa vakansiyani yoping yoki tarifni oshiring.",
                reply_markup=builder.as_markup(),
            )
            return
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
async def start_manual_edit(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    await state.clear()
    await state.update_data(editing_vacancy_key=key, vacancy_title=vacancy["title"],
                            pending_questions=vacancy["questions"])
    await state.set_state(AdminForm.reviewing_ai_questions)
    await _show_review(callback.message, vacancy["questions"])
    await callback.answer()


# ============================= 7) BITTA SAVOLNI ALOHIDA TAHRIRLASH =============================


@router.callback_query(F.data.startswith("vaceditlist:"))
async def show_question_picker(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
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
async def start_edit_single_question(
    callback: CallbackQuery, state: FSMContext, tenant_id: int
):
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[0] != "vaceditq" or not parts[2].isdecimal():
        await callback.answer("Noto'g'ri savol so'rovi.", show_alert=True)
        return
    key, idx_str = parts[1:]
    idx = int(idx_str)
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy or idx >= len(vacancy["questions"]):
        await callback.answer("Bu savol topilmadi.", show_alert=True)
        return

    current = vacancy["questions"][idx]
    await state.clear()
    await state.update_data(editing_vacancy_key=key, vacancy_title=vacancy["title"],
                            pending_questions=vacancy["questions"], editing_pending_index=idx)
    await callback.message.edit_text(
        f"✏️ <b>{idx + 1}-savol</b>\n\n{escape(current['text'])}\n\n"
        "Yangi savol matnini yozing. Keyin javob turini tugmadan tanlaysiz."
    )
    await state.set_state(AdminForm.editing_pending_question)
    await callback.answer()


@router.message(AdminForm.editing_single_question, F.text)
async def receive_single_question_edit(
    message: Message, state: FSMContext, tenant_id: int
):
    data = await state.get_data()
    key = data["editing_vacancy_key"]
    idx = data["editing_question_index"]

    parsed = parse_manual_questions(message.text)
    if not parsed:
        await message.answer("Savol matni bo'sh bo'lmasligi kerak. Qaytadan yozing.")
        return

    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy or idx >= len(vacancy["questions"]):
        await message.answer("Bu vakansiya yoki savol endi topilmadi.")
        await state.clear()
        return

    new_question = parsed[0]
    new_question["key"] = vacancy["questions"][idx].get("key", new_question["key"])
    updated_questions = list(vacancy["questions"])
    updated_questions[idx] = new_question

    await database.update_vacancy(tenant_id, key, questions=updated_questions)
    await state.clear()

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Vakansiyaga qaytish", callback_data=f"vac:{key}")
    await message.answer(
        f"✅ {idx + 1}-savol yangilandi.", reply_markup=builder.as_markup()
    )
