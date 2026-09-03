"""
Admin bot — suhbat vaqtlari (sana+soat), uchrashuv manzili, intervyuchi
kontakti va eslatma matnini boshqarish. Har biri shu MIJOZGA (tenant_id) xos.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database
from services.candidate_followup import notify_candidate_outcome

router = Router(name="admin_interview")


class InterviewForm(StatesGroup):
    adding_slot_label = State()
    adding_slot_capacity = State()
    setting_location = State()
    setting_interviewer_name = State()
    setting_interviewer_phone = State()
    setting_notes = State()


def _settings_summary(settings: dict) -> str:
    location = settings.get("location_text") or (
        f"({settings['location_lat']}, {settings['location_lng']})"
        if settings.get("location_lat")
        else "sozlanmagan"
    )
    return (
        f"📍 Manzil: {location}\n"
        f"👤 Intervyuchi: {settings.get('interviewer_name') or 'sozlanmagan'}\n"
        f"📞 Telefon: {settings.get('interviewer_phone') or 'sozlanmagan'}\n"
        f"📝 Eslatma: {settings.get('notes') or 'sozlanmagan'}"
    )


async def _show_menu(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    slots = await database.list_interview_slots(tenant_id, active_only=True)
    settings = await database.get_interview_settings(tenant_id)

    lines = ["📅 <b>Suhbat vaqtlari va sozlamalar</b>", ""]
    if slots:
        lines.append("<b>Mavjud vaqtlar:</b>")
        for s in slots:
            lines.append(f"• {s['label']} (sig'imi: {s['capacity']})")
    else:
        lines.append("Hozircha hech qanday vaqt qo'shilmagan.")
    lines.append("")
    lines.append(_settings_summary(settings))

    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Vaqt qo'shish", callback_data="ivslot:add")
    if slots:
        builder.button(text="🗑 Vaqtni o'chirish", callback_data="ivslot:dellist")
    builder.button(text="📍 Manzilni sozlash", callback_data="ivset:location")
    builder.button(text="👤 Intervyuchi ismi", callback_data="ivset:name")
    builder.button(text="📞 Intervyuchi raqami", callback_data="ivset:phone")
    builder.button(text="📝 Eslatma matni", callback_data="ivset:notes")
    builder.button(text="⬅️ Bosh menyu", callback_data="menu:main")
    builder.adjust(1)

    await message.answer("\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data == "menu:interview")
async def open_interview_menu(
    callback: CallbackQuery, state: FSMContext, tenant_id: int
):
    await callback.message.delete()
    await _show_menu(callback.message, state, tenant_id)
    await callback.answer()


@router.callback_query(F.data == "ivslot:add")
async def start_add_slot(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Yangi suhbat vaqtini yozing (sana va soat bilan birga), masalan:\n\n"
        "<code>22-avgust, soat 14:00</code>"
    )
    await state.set_state(InterviewForm.adding_slot_label)
    await callback.answer()


@router.message(InterviewForm.adding_slot_label, F.text)
async def receive_slot_label(message: Message, state: FSMContext):
    label = message.text.strip()
    if not 3 <= len(label) <= 80:
        await message.answer("Sana/vaqtni 3–80 belgi oralig'ida aniq yozing.")
        return
    await state.update_data(new_slot_label=label)
    await message.answer("Bu vaqtga nechta nomzod qabul qilinishi mumkin? (Odatda: 1)")
    await state.set_state(InterviewForm.adding_slot_capacity)


@router.message(InterviewForm.adding_slot_capacity, F.text)
async def receive_slot_capacity(message: Message, state: FSMContext, tenant_id: int):
    text = message.text.strip()
    if not text.isdigit() or not 1 <= int(text) <= 100:
        await message.answer("Sig'im 1 dan 100 gacha butun son bo'lishi kerak.")
        return

    data = await state.get_data()
    try:
        await database.add_interview_slot(
            tenant_id, data["new_slot_label"], capacity=int(text)
        )
    except database.InterviewSlotConflict:
        await message.answer("Bu suhbat vaqti allaqachon mavjud. Boshqa vaqt yozing.")
        await state.set_state(InterviewForm.adding_slot_label)
        return
    await message.answer(f"✅ Qo'shildi: {data['new_slot_label']} (sig'imi: {text})")
    await _show_menu(message, state, tenant_id)


@router.callback_query(F.data == "ivslot:dellist")
async def show_delete_slot_list(callback: CallbackQuery, tenant_id: int):
    slots = await database.list_interview_slots(tenant_id, active_only=True)
    builder = InlineKeyboardBuilder()
    for s in slots:
        builder.button(text=f"🗑 {s['label']}", callback_data=f"ivslot:del:{s['id']}")
    builder.button(text="⬅️ Orqaga", callback_data="menu:interview")
    builder.adjust(1)
    await callback.message.edit_text(
        "Qaysi vaqtni o'chirasiz?", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ivslot:del:"))
async def delete_slot(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    try:
        slot_id = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        await callback.answer("Noto'g'ri vaqt.", show_alert=True)
        return
    try:
        deleted = await database.delete_interview_slot(tenant_id, slot_id)
    except database.InterviewSlotBooked:
        await callback.answer(
            "Bu vaqtni nomzod tanlagan. Band suhbat vaqtini o'chirib bo'lmaydi.",
            show_alert=True,
        )
        return
    if not deleted:
        await callback.answer("Bu vaqt allaqachon o'chirilgan.", show_alert=True)
        return
    await callback.answer("O'chirildi.")
    await callback.message.delete()
    await _show_menu(callback.message, state, tenant_id)


@router.callback_query(F.data == "ivset:location")
async def start_set_location(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Uchrashuv manzilini yuboring — Telegram'ning 📎 → Location (Joylashuv) tugmasi "
        "orqali xaritadan tanlang, YOKI oddiy matn ko'rinishida yozing (masalan: "
        '"Toshkent sh., Chilonzor tumani, ... ko\'chasi 1-uy").'
    )
    await state.set_state(InterviewForm.setting_location)
    await callback.answer()


@router.message(InterviewForm.setting_location, F.location)
async def receive_location_pin(message: Message, state: FSMContext, tenant_id: int):
    await database.update_interview_settings(
        tenant_id,
        location_lat=message.location.latitude,
        location_lng=message.location.longitude,
        location_text=None,
    )
    await message.answer("✅ Manzil (xarita) saqlandi.")
    await _show_menu(message, state, tenant_id)


@router.message(InterviewForm.setting_location, F.text)
async def receive_location_text(message: Message, state: FSMContext, tenant_id: int):
    await database.update_interview_settings(
        tenant_id,
        location_text=message.text.strip(),
        location_lat=None,
        location_lng=None,
    )
    await message.answer("✅ Manzil saqlandi.")
    await _show_menu(message, state, tenant_id)


@router.callback_query(F.data == "ivset:name")
async def start_set_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Suhbatni o'tkazadigan insonning ismini yozing:")
    await state.set_state(InterviewForm.setting_interviewer_name)
    await callback.answer()


@router.message(InterviewForm.setting_interviewer_name, F.text)
async def receive_interviewer_name(message: Message, state: FSMContext, tenant_id: int):
    await database.update_interview_settings(
        tenant_id, interviewer_name=message.text.strip()
    )
    await message.answer("✅ Saqlandi.")
    await _show_menu(message, state, tenant_id)


@router.callback_query(F.data == "ivset:phone")
async def start_set_phone(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Suhbatni o'tkazadigan insonning telefon raqamini yozing:"
    )
    await state.set_state(InterviewForm.setting_interviewer_phone)
    await callback.answer()


@router.message(InterviewForm.setting_interviewer_phone, F.text)
async def receive_interviewer_phone(
    message: Message, state: FSMContext, tenant_id: int
):
    await database.update_interview_settings(
        tenant_id, interviewer_phone=message.text.strip()
    )
    await message.answer("✅ Saqlandi.")
    await _show_menu(message, state, tenant_id)


@router.callback_query(F.data == "ivset:notes")
async def start_set_notes(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Nomzodga suhbatdan oldin yuboriladigan eslatma matnini yozing (masalan: "
        '"Iltimos, belgilangan vaqtda kechikmasdan keling va pasportingizni olib keling."):'
    )
    await state.set_state(InterviewForm.setting_notes)
    await callback.answer()


@router.message(InterviewForm.setting_notes, F.text)
async def receive_notes(message: Message, state: FSMContext, tenant_id: int):
    await database.update_interview_settings(tenant_id, notes=message.text.strip())
    await message.answer("✅ Saqlandi.")
    await _show_menu(message, state, tenant_id)


@router.callback_query(F.data.startswith("ivoutcome:"))
async def interview_outcome(callback: CallbackQuery, tenant_id: int):
    try:
        _, app_id_raw, outcome = callback.data.split(":", 2)
        app_id = int(app_id_raw)
    except (TypeError, ValueError):
        await callback.answer("Noto'g'ri amal.", show_alert=True)
        return
    if outcome not in {"hired", "not_hired", "no_show"}:
        await callback.answer("Noto'g'ri natija.", show_alert=True)
        return
    changed = await database.transition_application_status(
        tenant_id, app_id, outcome, {"accepted"}
    )
    if not changed:
        await callback.answer("Bu suhbat natijasi allaqachon belgilangan.", show_alert=True)
        return
    await notify_candidate_outcome(tenant_id, app_id, outcome)
    labels = {"hired": "Ishga olindi", "not_hired": "Ishga olinmadi", "no_show": "Suhbatga kelmadi"}
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001 - natija DBda saqlangan; eski xabarni edit qilish kritik emas
        await callback.answer(f"✅ {labels[outcome]}")
        return
    await callback.answer(f"✅ {labels[outcome]}")
