"""Admin bot — asosiy menyu va statistika."""
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import BOT_TOKEN
from services import database

router = Router(name="admin_menu")


def _is_founder_tenant(tenant: dict | None) -> bool:
    """Faqat ASOSCHINING O'Z tenanti uchun True — boshqa mijozlar Janob
    HR'ning o'z sotuv lidlarini ko'rmasligi kerak."""
    return bool(tenant and tenant.get("bot_token") == BOT_TOKEN)


def _main_menu_keyboard(is_founder: bool = False):
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Vakansiyalar", callback_data="menu:vacancies")
    builder.button(text="➕ Yangi vakansiya", callback_data="menu:new")
    builder.button(text="📅 Suhbat vaqtlari", callback_data="menu:interview")
    builder.button(text="📊 Statistika", callback_data="menu:stats")
    if is_founder:
        builder.button(text="🎯 Lidlar", callback_data="menu:leads")
    builder.adjust(1)
    return builder.as_markup()


async def show_main_menu(message: Message, is_founder: bool = False):
    await message.answer(
        "👔 <b>Janob HR — Admin panel</b>\n\n"
        "HR jarayoningizni shu yerdan boshqaring: vakansiyalar, arizalar, "
        "suhbat rejasi va statistika.\n\nQuyidagilardan birini tanlang:",
        reply_markup=_main_menu_keyboard(is_founder),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, tenant: dict = None):
    await state.clear()
    await show_main_menu(message, is_founder=_is_founder_tenant(tenant))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, tenant: dict = None):
    await state.clear()
    await show_main_menu(message, is_founder=_is_founder_tenant(tenant))


@router.callback_query(F.data == "menu:main")
async def back_to_main(callback: CallbackQuery, state: FSMContext, tenant: dict = None):
    await state.clear()
    await callback.message.edit_text(
        "👔 <b>Janob HR — Admin panel</b>\n\nQuyidagilardan birini tanlang:",
        reply_markup=_main_menu_keyboard(_is_founder_tenant(tenant)),
    )
    await callback.answer()


@router.callback_query(F.data == "menu:leads")
async def show_leads(callback: CallbackQuery, tenant: dict = None):
    # Ehtiyot chorasi: faqat asoschining o'z admin-boti orqali ruxsat —
    # tugma boshqalarga umuman ko'rsatilmaydi, lekin himoyani ikki marta
    # tekshirish zarar qilmaydi.
    if not _is_founder_tenant(tenant):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    leads = await database.list_leads(limit=20)
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="menu:main")

    if not leads:
        await callback.message.edit_text(
            "🎯 <b>Lidlar</b>\n\nHozircha hech qanday lid yo'q.",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    lines = ["🎯 <b>Lidlar</b> (oxirgi 20 tasi)", ""]
    for lead in leads:
        status_icon = "✅" if lead["status"] == "mijozga aylandi" else "🟡"
        created = (lead["created_at"] or "")[:16].replace("T", " ")
        username_part = f" (@{lead['telegram_username']})" if lead.get("telegram_username") else ""
        lines.append(
            f"{status_icon} <b>{lead['company_name'] or '-'}</b> — {lead['status']}\n"
            f"   {lead['full_name'] or '-'} | {lead['phone'] or '-'}\n"
            f"   Telegram: <code>{lead['telegram_user_id']}</code>{username_part}\n"
            f"   {created}"
        )
    text = "\n\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n\n…(qisqartirildi)"

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def show_stats(callback: CallbackQuery, tenant_id: int):
    overall = await database.get_overall_stats(tenant_id)
    per_vacancy = await database.get_vacancy_stats(tenant_id)

    lines = [
        "📊 <b>Umumiy statistika</b>",
        "",
        f"👆 Botni boshlaganlar: <b>{overall['starts_unique']}</b> kishi"
        + (f" ({overall['starts_total']} marta)" if overall['starts_total'] != overall['starts_unique'] else ""),
        f"📥 Ariza topshirganlar: <b>{overall['total']}</b>"
        + (f" ({overall['conversion_percent']}% konversiya)" if overall['conversion_percent'] is not None else ""),
        "",
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
