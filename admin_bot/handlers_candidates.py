"""Admin bot — yangi va barcha nomzodlarni sahifalab ko'rish."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from handlers.admin import format_application_full_text, format_candidate_card
from services import database
from services.ai_scoring import aggregate_scores

router = Router(name="admin_candidates")
PAGE_SIZE = 5

_STATUS = {
    "pending": "🆕 Yangi",
    "saved": "🟡 Keyin ko'rish",
    "accepted": "📅 Suhbatga chaqirilgan",
    "declined": "❌ Rad etilgan",
    "rejected_hard_filter": "⛔ Filtrdan o'tmagan",
    "rejected_irrelevant": "⛔ Mos kelmagan",
    "rejected_ai_generated": "⛔ Shubhali javob",
    "hired": "✅ Ishga olindi",
    "not_hired": "❌ Ishga olinmadi",
    "no_show": "🚫 Suhbatga kelmadi",
}


async def _show_list(callback: CallbackQuery, tenant_id: int, status: str, page: int):
    db_status = None if status == "all" else status
    page = max(page, 0)
    apps, total = await database.list_applications(
        tenant_id, status=db_status, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )
    title = "📥 Yangi arizalar" if status == "pending" else "👥 Barcha nomzodlar"
    builder = InlineKeyboardBuilder()
    for app in apps:
        score = aggregate_scores(app.get("ai_scores") or {})
        score_text = f" · {score['avg_score']}/100" if score else ""
        builder.button(
            text=f"{app['full_name']} · {app['vacancy_title']}{score_text}",
            callback_data=f"apps:view:{app['id']}:{status}:{page}",
        )
    if page > 0:
        builder.button(text="⬅️ Oldingi", callback_data=f"apps:list:{status}:{page - 1}")
    if (page + 1) * PAGE_SIZE < total:
        builder.button(text="Keyingi ➡️", callback_data=f"apps:list:{status}:{page + 1}")
    builder.button(text="⬅️ Bosh menyu", callback_data="menu:main")
    builder.adjust(1)
    text = f"{title}\n\nJami: <b>{total}</b>"
    if not apps:
        text += "\n\nHozircha bu bo'limda nomzod yo'q."
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


async def show_list_message(message: Message, tenant_id: int, status: str, page: int):
    db_status = None if status == "all" else status
    apps, total = await database.list_applications(
        tenant_id, status=db_status, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )
    title = "📥 Yangi arizalar" if status == "pending" else "👥 Barcha nomzodlar"
    builder = InlineKeyboardBuilder()
    for app in apps:
        score = aggregate_scores(app.get("ai_scores") or {})
        score_text = f" · {score['avg_score']}/100" if score else ""
        builder.button(
            text=f"{app['full_name']} · {app['vacancy_title']}{score_text}",
            callback_data=f"apps:view:{app['id']}:{status}:{page}",
        )
    builder.adjust(1)
    text = f"{title}\n\nJami: <b>{total}</b>"
    if not apps:
        text += "\n\nHozircha bu bo'limda nomzod yo'q."
    await message.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("apps:list:"))
async def list_candidates(callback: CallbackQuery, tenant_id: int):
    _, _, status, page = callback.data.split(":")
    await _show_list(callback, tenant_id, status, int(page))


@router.callback_query(F.data.startswith("apps:view:"))
async def view_candidate(callback: CallbackQuery, tenant_id: int):
    _, _, app_id, status, page = callback.data.split(":")
    app = await database.get_application(tenant_id, int(app_id))
    if not app:
        await callback.answer("Nomzod topilmadi.", show_alert=True)
        return
    text = format_candidate_card(app)
    text += f"\n\n📌 {_STATUS.get(app['status'], app['status'])}"

    builder = InlineKeyboardBuilder()
    if app["status"] in {"pending", "saved"}:
        builder.button(text="✅ Suhbatga", callback_data=f"decision:accept:{app_id}")
        builder.button(text="🟡 Keyin ko'rish", callback_data=f"decision:save:{app_id}")
        builder.button(text="❌ Rad etish", callback_data=f"decision:reject:{app_id}")
    builder.button(
        text="📋 To'liq javoblar", callback_data=f"apps:full:{app_id}:{status}:{page}"
    )
    builder.button(text="⬅️ Ro'yxat", callback_data=f"apps:list:{status}:{page}")
    builder.adjust(2, 1, 1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("apps:full:"))
async def view_full_answers(callback: CallbackQuery, tenant_id: int):
    _, _, app_id, status, page = callback.data.split(":")
    app = await database.get_application(tenant_id, int(app_id))
    if not app:
        await callback.answer("Nomzod topilmadi.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(
        text="⬅️ Qisqa karta", callback_data=f"apps:view:{app_id}:{status}:{page}"
    )
    await callback.message.edit_text(
        await format_application_full_text(app), reply_markup=builder.as_markup()
    )
    await callback.answer()
