"""Admin bot — asosiy menyu va statistika."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database

router = Router(name="admin_menu")


def _main_menu_keyboard(overall: dict):
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"📥 Yangi arizalar · {overall['pending']}",
        callback_data="apps:list:pending:0",
    )
    builder.button(text="👥 Barcha nomzodlar", callback_data="apps:list:all:0")
    builder.button(text="💼 Vakansiyalar", callback_data="menu:vacancies")
    builder.button(text="📅 Suhbatlar", callback_data="menu:interview")
    builder.button(text="📊 Hisobot", callback_data="menu:stats")
    builder.button(text="💳 Tarif va limitlar", callback_data="menu:billing")
    builder.button(text="➕ Yangi vakansiya", callback_data="menu:new")
    builder.adjust(1, 1, 2, 1, 1)
    return builder.as_markup()


async def show_main_menu(message: Message, tenant_id: int, *, edit: bool = False):
    overall = await database.get_overall_stats(tenant_id)
    text = (
        "👔 <b>Janob HR · Ishga qabul</b>\n\n"
        f"Yangi: <b>{overall['pending']}</b>   ·   "
        f"Suhbatga: <b>{overall['accepted']}</b>   ·   "
        f"Jami: <b>{overall['total']}</b>\n\n"
        "Bugungi ishni qayerdan boshlaysiz?"
    )
    method = message.edit_text if edit else message.answer
    await method(text, reply_markup=_main_menu_keyboard(overall))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(message, tenant_id)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(message, tenant_id)


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(callback.message, tenant_id, edit=True)
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
