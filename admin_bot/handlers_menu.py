"""Admin bot — asosiy menyu va statistika."""

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import MINI_APP_BASE_URL, WEBHOOK_BASE_URL
from services import database

router = Router(name="admin_menu")

ADMIN_MENU = {
    "panel": "🖥 Boshqaruv paneli",
    "new": "📥 Yangi arizalar",
    "candidates": "👥 Nomzodlar",
    "vacancies": "💼 Vakansiyalar",
    "interviews": "📅 Suhbatlar",
    "stats": "📊 Statistika",
    "billing": "💳 Tarif va to'lov",
    "help": "☎️ Yordam",
}


def _service_keyboard(tenant_id: int) -> ReplyKeyboardMarkup:
    # Reply-keyboard WebApp tugmasi ayrim Telegram klientlarida SimpleWebView
    # sifatida ochilib, server auth uchun kerakli initData'ni bermasligi mumkin.
    # Shuning uchun persistent tugma oddiy matn; bosilganda quyidagi handler
    # signed initData beradigan inline WebApp tugmasini yuboradi.
    panel = KeyboardButton(text=ADMIN_MENU["panel"])
    return ReplyKeyboardMarkup(
        keyboard=[
            [panel],
            [KeyboardButton(text=ADMIN_MENU["new"]), KeyboardButton(text=ADMIN_MENU["candidates"])],
            [KeyboardButton(text=ADMIN_MENU["vacancies"]), KeyboardButton(text=ADMIN_MENU["interviews"])],
            [KeyboardButton(text=ADMIN_MENU["stats"]), KeyboardButton(text=ADMIN_MENU["billing"])],
            [KeyboardButton(text=ADMIN_MENU["help"])],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Kerakli xizmatni tanlang",
    )


def _main_menu_keyboard(overall: dict, tenant_id: int):
    builder = InlineKeyboardBuilder()
    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")
    if WEBHOOK_BASE_URL:
        builder.button(
            text="🖥 Boshqaruv paneli",
            web_app=WebAppInfo(url=f"{miniapp_base}/{tenant_id}"),
        )
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
    builder.adjust(1, 1, 1, 2, 1, 1, 1)
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
    if edit:
        await message.edit_text(text, reply_markup=_main_menu_keyboard(overall, tenant_id))
    else:
        await message.answer(text, reply_markup=_service_keyboard(tenant_id))


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(message, tenant_id)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, tenant_id: int):
    await state.clear()
    await show_main_menu(message, tenant_id)


@router.message(F.text == ADMIN_MENU["panel"])
async def service_panel(message: Message, tenant_id: int):
    if not WEBHOOK_BASE_URL:
        await message.answer("Boshqaruv paneli vaqtincha mavjud emas. Keyinroq urinib ko'ring.")
        return
    miniapp_base = (MINI_APP_BASE_URL or f"{WEBHOOK_BASE_URL}/miniapp").rstrip("/")
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🖥 Boshqaruv panelini ochish",
        web_app=WebAppInfo(url=f"{miniapp_base}/{tenant_id}"),
    )
    await message.answer(
        "Boshqaruv panelini Telegram orqali xavfsiz oching:",
        reply_markup=builder.as_markup(),
    )


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


async def _send_stats(message: Message, tenant_id: int):
    overall = await database.get_overall_stats(tenant_id)
    await message.answer(
        "📊 <b>Statistika</b>\n\n"
        f"Jami ariza: <b>{overall['total']}</b>\n"
        f"Yangi: <b>{overall['pending']}</b>\n"
        f"Suhbatga chaqirilgan: <b>{overall['accepted']}</b>\n"
        f"Rad etilgan: <b>{overall['rejected_total']}</b>"
    )


@router.message(F.text == ADMIN_MENU["new"])
async def service_new_applications(message: Message, tenant_id: int):
    from admin_bot.handlers_candidates import show_list_message
    await show_list_message(message, tenant_id, "pending", 0)


@router.message(F.text == ADMIN_MENU["candidates"])
async def service_candidates(message: Message, tenant_id: int):
    from admin_bot.handlers_candidates import show_list_message
    await show_list_message(message, tenant_id, "all", 0)


@router.message(F.text == ADMIN_MENU["vacancies"])
async def service_vacancies(message: Message, tenant_id: int):
    from admin_bot.handlers_vacancy_list import list_vacancies_message
    await list_vacancies_message(message, tenant_id)


@router.message(F.text == ADMIN_MENU["interviews"])
async def service_interviews(message: Message, state: FSMContext, tenant_id: int):
    from admin_bot.handlers_interview import _show_menu
    await _show_menu(message, state, tenant_id)


@router.message(F.text == ADMIN_MENU["billing"])
async def service_billing(message: Message, tenant_id: int):
    from admin_bot.handlers_billing import show_billing_message
    await show_billing_message(message, tenant_id)


@router.message(F.text == ADMIN_MENU["stats"])
async def service_stats(message: Message, tenant_id: int):
    await _send_stats(message, tenant_id)


@router.message(F.text == ADMIN_MENU["help"])
async def service_help(message: Message):
    await message.answer(
        "☎️ <b>Yordam</b>\n\nSavol yoki muammo bo'lsa, <b>@F45746</b> ga yozing."
    )
