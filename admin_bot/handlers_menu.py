"""Admin bot — asosiy menyu va statistika."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database

router = Router(name="admin_menu")


def _main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Vakansiyalar", callback_data="menu:vacancies")
    builder.button(text="➕ Yangi vakansiya", callback_data="menu:new")
    builder.button(text="📅 Suhbat vaqtlari", callback_data="menu:interview")
    builder.button(text="📊 Statistika", callback_data="menu:stats")
    builder.adjust(1)
    return builder.as_markup()


async def show_main_menu(message: Message):
    await message.answer(
        "👔 <b>Janob HR — Admin panel</b>\n\n"
        "HR jarayoningizni shu yerdan boshqaring: vakansiyalar, arizalar, "
        "suhbat rejasi va statistika.\n\nQuyidagilardan birini tanlang:",
        reply_markup=_main_menu_keyboard(),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await show_main_menu(message)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await show_main_menu(message)


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "👔 <b>Janob HR — Admin panel</b>\n\nQuyidagilardan birini tanlang:",
        reply_markup=_main_menu_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def show_stats(callback: CallbackQuery, tenant_id: int):
    overall = await database.get_overall_stats(tenant_id)
    per_vacancy = await database.get_vacancy_stats(tenant_id)

    lines = [
        "📊 <b>Umumiy statistika</b>",
        "",
        f"📥 Jami ariza: <b>{overall['total']}</b>",
        f"⏳ Kutilmoqda: {overall['pending']}",
        f"✅ Qabul qilingan: {overall['accepted']}",
        f"❌ Rad etilgan (jami): {overall['rejected_total']}",
        f"   • Admin tomonidan: {overall['declined_by_admin']}",
        f"   • Talabga javob bermadi: {overall['rejected_hard_filter']}",
        f"   • Mavzuga mos kelmadi: {overall['rejected_irrelevant']}",
        f"   • AI orqali yozilgan deb topildi: {overall['rejected_ai_generated']}",
    ]

    if per_vacancy:
        lines.append("")
        lines.append("<b>Vakansiyalar bo'yicha:</b>")
        for v in per_vacancy:
            lines.append(
                f"\n<b>{v['vacancy_title']}</b>\n"
                f"  Jami: {v['total']} | Kutilmoqda: {v['pending']} | "
                f"Qabul: {v['accepted']} | Rad: {v['rejected']}"
            )

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="menu:main")

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()
