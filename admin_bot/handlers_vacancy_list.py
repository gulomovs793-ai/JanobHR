"""Admin bot — vakansiyalar ro'yxati, tafsilotlari, faollashtirish/o'chirish."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin_bot.parsing import format_questions_preview
from services import database
from services.ai_scoring import aggregate_scores

router = Router(name="admin_vacancy_list")


@router.callback_query(F.data == "menu:vacancies")
async def list_vacancies(callback: CallbackQuery, tenant_id: int):
    vacancies = await database.list_vacancies(tenant_id, active_only=False)

    builder = InlineKeyboardBuilder()
    if not vacancies:
        text = "Hozircha hech qanday vakansiya yo'q."
    else:
        text = "📋 <b>Vakansiyalar</b>\n\nBiror birini tanlang:"
        for v in vacancies:
            status = "🟢" if v["active"] else "🔴"
            builder.button(
                text=f"{status} {v['title']}", callback_data=f"vac:{v['key']}"
            )
    builder.button(text="➕ Yangi vakansiya", callback_data="menu:new")
    builder.button(text="⬅️ Orqaga", callback_data="menu:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


async def _show_vacancy_detail(callback: CallbackQuery, tenant_id: int, key: str):
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer(
            "Bu vakansiya topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True
        )
        return

    stats_list = await database.get_vacancy_stats(tenant_id)
    stats = next((s for s in stats_list if s["vacancy_key"] == key), None)

    status = "🟢 Faol" if vacancy["active"] else "🔴 Faolsiz"
    resume_text = "Ha" if vacancy["resume_required"] else "Yo'q"
    lines = [
        f"<b>{vacancy['title']}</b>",
        f"Holat: {status}",
        f"Rezyume talab qilinadi: {resume_text}",
        "",
        f"<b>Savollar ({len(vacancy['questions'])} ta):</b>",
        format_questions_preview(vacancy["questions"]),
    ]
    if stats:
        lines.append("")
        lines.append(
            f"📊 Jami: {stats['total']} | Kutilmoqda: {stats['pending']} | "
            f"Qabul: {stats['accepted']} | Rad: {stats['rejected']}"
        )

    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 Faolsizlantirish" if vacancy["active"] else "🟢 Faollashtirish"
    builder.button(text=toggle_text, callback_data=f"vactoggle:{key}")
    builder.button(text="🏆 Eng yaxshi nomzodlar", callback_data=f"vacranking:{key}")
    builder.button(text="📥 Excel yuklab olish", callback_data=f"vacexport:{key}")
    builder.button(
        text="🔄 Savollarni AI bilan yangilash", callback_data=f"vacregen:{key}"
    )
    builder.button(
        text="✏️ Bitta savolni tahrirlash", callback_data=f"vaceditlist:{key}"
    )
    builder.button(
        text="✍️ Savollarni to'liq qayta yozish", callback_data=f"vacmanual:{key}"
    )
    builder.button(text="🗑 O'chirish", callback_data=f"vacdel:{key}")
    builder.button(text="⬅️ Ro'yxatga qaytish", callback_data="menu:vacancies")
    builder.adjust(1)

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("vac:"))
async def vacancy_detail(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    await _show_vacancy_detail(callback, tenant_id, key)


@router.callback_query(F.data.startswith("vactoggle:"))
async def toggle_vacancy(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return
    await database.update_vacancy(tenant_id, key, active=not vacancy["active"])
    await _show_vacancy_detail(callback, tenant_id, key)


@router.callback_query(F.data.startswith("vacdel:"))
async def confirm_delete(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(
        text="⚠️ Ha, butunlay o'chirish", callback_data=f"vacdelconfirm:{key}"
    )
    builder.button(text="Bekor qilish", callback_data=f"vac:{key}")
    builder.adjust(1)

    await callback.message.edit_text(
        f"<b>{vacancy['title']}</b> vakansiyasini butunlay o'chirmoqchimisiz?\n\n"
        "⚠️ Bu amalni ortga qaytarib bo'lmaydi. Eski arizalar statistikada saqlanib "
        "qoladi, lekin nomzodlar bu vakansiyani endi ko'ra olmaydi.\n\n"
        "Agar shunchaki vaqtincha yopmoqchi bo'lsangiz, o'rniga \"Faolsizlantirish\"ni ishlating.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("vacdelconfirm:"))
async def delete_vacancy(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    await database.delete_vacancy(tenant_id, key)
    await callback.answer("Vakansiya o'chirildi.", show_alert=True)
    await list_vacancies(callback, tenant_id)


_VERDICT_EMOJI = {"yashil": "🟢", "sariq": "🟡", "qizil": "🔴"}
_STATUS_LABELS = {
    "pending": "⏳ Kutilmoqda",
    "accepted": "✅ Qabul qilingan",
    "declined": "❌ Rad etilgan",
    "rejected_hard_filter": "❌ Talabga javob bermadi",
    "rejected_irrelevant": "❌ Mavzuga mos kelmadi",
}


@router.callback_query(F.data.startswith("vacranking:"))
async def show_ranking(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    apps = await database.get_applications_for_vacancy(tenant_id, key)

    scored = []
    for app in apps:
        aggregate = aggregate_scores(app.get("ai_scores") or {})
        if aggregate:
            scored.append((aggregate, app))

    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data=f"vac:{key}")

    if not scored:
        await callback.message.edit_text(
            f"🏆 <b>{vacancy['title']}</b> — hozircha AI baholagan nomzod yo'q.",
            reply_markup=builder.as_markup(),
        )
        await callback.answer()
        return

    scored.sort(key=lambda pair: pair[0]["avg_score"], reverse=True)

    lines = [f"🏆 <b>{vacancy['title']}</b> — eng yaxshi nomzodlar:", ""]
    for rank, (aggregate, app) in enumerate(scored[:15], 1):
        emoji = _VERDICT_EMOJI.get(aggregate["verdict"], "⚪")
        status_label = _STATUS_LABELS.get(app["status"], app["status"])
        phone = f" | {app['phone_number']}" if app.get("phone_number") else ""
        lines.append(
            f"{rank}. {emoji} <b>{aggregate['avg_score']}/100</b> — {app['full_name']}"
            f" (@{app['username'] or '—'}{phone})\n   {status_label}"
        )

    text = "\n".join(lines)
    if len(text) > 3900:
        text = text[:3900] + "\n\n… (ro'yxat qisqartirildi)"

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()
