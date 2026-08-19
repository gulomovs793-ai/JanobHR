"""
Admin bot — suhbat vaqtlari (sana+soat), uchrashuv manzili, intervyuchi
kontakti va eslatma matnini boshqarish. Bular globaldir (barcha vakansiyalar
uchun umumiy).
"""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database

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
        f"({settings['location_lat']}, {settings['location_lng']})" if settings.get("location_lat") else "sozlanmagan"
    )
    return (
        f"📍 Manzil: {location}\n"
        f"👤 Intervyuchi: {settings.get('interviewer_name') or 'sozlanmagan'}\n"
        f"📞 Telefon: {settings.get('interviewer_phone') or 'sozlanmagan'}\n"
        f"📝 Eslatma: {settings.get('notes') or 'sozlanmagan'}"
    )


async def _show_menu(message: Message, state: FSMContext):
    await state.clear()
    slots = await database.list_interview_slots(active_only=True)
    settings = await database.get_interview_settings()

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
async def open_interview_menu(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await _show_menu(callback.message, state)
    await callback.answer()


# --- Vaqt qo'shish ---

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
    await state.update_data(new_slot_label=message.text.strip())
    await message.answer("Bu vaqtga nechta nomzod qabul qilinishi mumkin? (Odatda: 1)")
    await state.set_state(InterviewForm.adding_slot_capacity)


@router.message(InterviewForm.adding_slot_capacity, F.text)
async def receive_slot_capacity(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) < 1:
        await message.answer("Iltimos, musbat butun son kiriting (masalan: 1).")
        return

    data = await state.get_data()
    await database.add_interview_slot(data["new_slot_label"], capacity=int(text))
    await message.answer(f"✅ Qo'shildi: {data['new_slot_label']} (sig'imi: {text})")
    await _show_menu(message, state)


# --- Vaqtni o'chirish ---

@router.callback_query(F.data == "ivslot:dellist")
async def show_delete_slot_list(callback: CallbackQuery):
    slots = await database.list_interview_slots(active_only=True)
    builder = InlineKeyboardBuilder()
    for s in slots:
        builder.button(text=f"🗑 {s['label']}", callback_data=f"ivslot:del:{s['id']}")
    builder.button(text="⬅️ Orqaga", callback_data="menu:interview")
    builder.adjust(1)
    await callback.message.edit_text("Qaysi vaqtni o'chirasiz?", reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("ivslot:del:"))
async def delete_slot(callback: CallbackQuery, state: FSMContext):
    slot_id = int(callback.data.split(":")[2])
    await database.delete_interview_slot(slot_id)
    await callback.answer("O'chirildi.")
    await callback.message.delete()
    await _show_menu(callback.message, state)


# --- Manzil ---

@router.callback_query(F.data == "ivset:location")
async def start_set_location(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Uchrashuv manzilini yuboring — Telegram'ning 📎 → Location (Joylashuv) tugmasi "
        "orqali xaritadan tanlang, YOKI oddiy matn ko'rinishida yozing (masalan: "
        "\"Toshkent sh., Chilonzor tumani, ... ko'chasi 1-uy\")."
    )
    await state.set_state(InterviewForm.setting_location)
    await callback.answer()


@router.message(InterviewForm.setting_location, F.location)
async def receive_location_pin(message: Message, state: FSMContext):
    await database.update_interview_settings(
        location_lat=message.location.latitude,
        location_lng=message.location.longitude,
        location_text=None,
    )
    await message.answer("✅ Manzil (xarita) saqlandi.")
    await _show_menu(message, state)


@router.message(InterviewForm.setting_location, F.text)
async def receive_location_text(message: Message, state: FSMContext):
    await database.update_interview_settings(
        location_text=message.text.strip(), location_lat=None, location_lng=None,
    )
    await message.answer("✅ Manzil saqlandi.")
    await _show_menu(message, state)


# --- Intervyuchi ismi ---

@router.callback_query(F.data == "ivset:name")
async def start_set_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Suhbatni o'tkazadigan insonning ismini yozing:")
    await state.set_state(InterviewForm.setting_interviewer_name)
    await callback.answer()


@router.message(InterviewForm.setting_interviewer_name, F.text)
async def receive_interviewer_name(message: Message, state: FSMContext):
    await database.update_interview_settings(interviewer_name=message.text.strip())
    await message.answer("✅ Saqlandi.")
    await _show_menu(message, state)


# --- Intervyuchi telefon raqami ---

@router.callback_query(F.data == "ivset:phone")
async def start_set_phone(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Suhbatni o'tkazadigan insonning telefon raqamini yozing:")
    await state.set_state(InterviewForm.setting_interviewer_phone)
    await callback.answer()


@router.message(InterviewForm.setting_interviewer_phone, F.text)
async def receive_interviewer_phone(message: Message, state: FSMContext):
    await database.update_interview_settings(interviewer_phone=message.text.strip())
    await message.answer("✅ Saqlandi.")
    await _show_menu(message, state)


# --- Eslatma matni ---

@router.callback_query(F.data == "ivset:notes")
async def start_set_notes(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "Nomzodga suhbatdan oldin yuboriladigan eslatma matnini yozing (masalan: "
        "\"Iltimos, belgilangan vaqtda kechikmasdan keling va pasportingizni olib keling.\"):"
    )
    await state.set_state(InterviewForm.setting_notes)
    await callback.answer()


@router.message(InterviewForm.setting_notes, F.text)
async def receive_notes(message: Message, state: FSMContext):
    await database.update_interview_settings(notes=message.text.strip())
    await message.answer("✅ Saqlandi.")
    await _show_menu(message, state)
