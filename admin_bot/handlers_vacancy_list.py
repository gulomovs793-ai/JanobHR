"""Admin bot — vakansiyalar ro'yxati, tafsilotlari, faollashtirish/o'chirish."""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from admin_bot.parsing import format_questions_preview
from services import database
from services.ai_scoring import aggregate_scores

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_vacancy_list")


async def _get_bot_username(tenant: dict | None, tenant_id: int) -> str | None:
    """`tenant.bot_username`ni qaytaradi. Ba'zi tenantlar (masalan
    asoschining o'zi, `_ensure_founder_tenant` orqali yaratilgan) oddiy
    faollashtirish oqimidan chetlab o'tgani uchun bu maydon bo'sh qolishi
    mumkin — shunday holatda jonli olib, keyingi safar uchun saqlab qo'yamiz
    (o'z-o'zini tuzatuvchi)."""
    if not tenant:
        return None
    bot_username = tenant.get("bot_username")
    if bot_username or not tenant.get("bot_token"):
        return bot_username

    try:
        from aiogram import Bot

        temp_bot = Bot(token=tenant["bot_token"])
        try:
            me = await temp_bot.get_me()
            await database.update_tenant_status(tenant_id, tenant["status"], bot_username=me.username)
            return me.username
        finally:
            await temp_bot.session.close()
    except Exception:
        logger.exception("Bot username'ini jonli olib bo'lmadi (tenant_id=%s).", tenant_id)
        return None


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
            builder.button(text=f"{status} {v['title']}", callback_data=f"vac:{v['key']}")
    builder.button(text="➕ Yangi vakansiya", callback_data="menu:new")
    builder.button(text="⬅️ Orqaga", callback_data="menu:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


async def _show_vacancy_detail(callback: CallbackQuery, tenant_id: int, key: str):
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return

    tenant = await database.get_tenant(tenant_id)
    bot_username = await _get_bot_username(tenant, tenant_id)

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
    if bot_username and vacancy["active"]:
        lines.append("")
        lines.append(f"🔗 <b>Ariza havolasi</b> (e'lonlarga qo'ying):\nhttps://t.me/{bot_username}?start=vac_{key}")

    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 Faolsizlantirish" if vacancy["active"] else "🟢 Faollashtirish"
    # QISQARTIRILGAN asosiy menyu: faqat eng ko'p kerak bo'ladigan 4 ta amal.
    # Savollarni tahrirlashga oid 3 ta amal + o'chirish alohida "✏️ Tahrirlash"
    # submenyusiga ko'chirildi (_show_edit_menu) — bu yerda ortiqcha tugma yo'q.
    builder.button(text="🏆 Eng yaxshi nomzodlar", callback_data=f"vacranking:{key}")
    builder.button(text="📥 Excel yuklab olish", callback_data=f"vacexport:{key}")
    if bot_username and vacancy["active"]:
        builder.button(text="📱 QR-kod olish", callback_data=f"vacqr:{key}")
    builder.button(text="✏️ Tahrirlash", callback_data=f"vacedit:{key}")
    builder.button(text=toggle_text, callback_data=f"vactoggle:{key}")
    builder.button(text="⬅️ Ro'yxatga qaytish", callback_data="menu:vacancies")
    builder.adjust(1)

    await callback.message.edit_text("\n".join(lines), reply_markup=builder.as_markup())
    await callback.answer()


async def _show_edit_menu(callback: CallbackQuery, tenant_id: int, key: str):
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi (o'chirilgan bo'lishi mumkin).", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Savollarni AI bilan yangilash", callback_data=f"vacregen:{key}")
    builder.button(text="✏️ Bitta savolni tahrirlash", callback_data=f"vaceditlist:{key}")
    builder.button(text="✍️ Savollarni to'liq qayta yozish", callback_data=f"vacmanual:{key}")
    builder.button(text="🧹 Arizalarni tozalash", callback_data=f"vacclearapps:{key}")
    builder.button(text="🗑 O'chirish", callback_data=f"vacdel:{key}")
    builder.button(text="⬅️ Orqaga", callback_data=f"vac:{key}")
    builder.adjust(1)

    await callback.message.edit_text(
        f"✏️ <b>{vacancy['title']}</b> — savollarni tahrirlash:",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("vac:"))
async def vacancy_detail(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    await _show_vacancy_detail(callback, tenant_id, key)


@router.callback_query(F.data.startswith("vacedit:"))
async def edit_menu(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    await _show_edit_menu(callback, tenant_id, key)


@router.callback_query(F.data.startswith("vactoggle:"))
async def toggle_vacancy(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return
    await database.update_vacancy(tenant_id, key, active=not vacancy["active"])
    await _show_vacancy_detail(callback, tenant_id, key)


@router.callback_query(F.data.startswith("vacqr:"))
async def send_qr_code(callback: CallbackQuery, tenant_id: int):
    import io

    import qrcode
    from aiogram.types import BufferedInputFile

    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    tenant = await database.get_tenant(tenant_id)
    bot_username = await _get_bot_username(tenant, tenant_id)
    if not vacancy or not bot_username:
        await callback.answer("Havola topilmadi.", show_alert=True)
        return

    link = f"https://t.me/{bot_username}?start=vac_{key}"
    img = qrcode.make(link, box_size=10, border=2)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    await callback.message.answer_photo(
        BufferedInputFile(buffer.read(), filename=f"{key}_qr.png"),
        caption=f"📱 <b>{vacancy['title']}</b>\n\nBu QR-kodni e'lon/plakat/vitrinaga bosib chiqaring — "
        "skanerlagan kishi to'g'ridan-to'g'ri shu vakansiyaga ariza topshirishni boshlaydi.",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("vacdel:"))
async def confirm_delete(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ Ha, butunlay o'chirish", callback_data=f"vacdelconfirm:{key}")
    builder.button(text="Bekor qilish", callback_data=f"vacedit:{key}")
    builder.adjust(1)

    await callback.message.edit_text(
        f"<b>{vacancy['title']}</b> vakansiyasini butunlay o'chirmoqchimisiz?\n\n"
        "⚠️ Bu amalni ortga qaytarib bo'lmaydi. Eski arizalar statistikada saqlanib "
        "qoladi, lekin nomzodlar bu vakansiyani endi ko'ra olmaydi.\n\n"
        "Agar shunchaki vaqtincha yopmoqchi bo'lsangiz, o'rniga \"Faolsizlantirish\"ni ishlating.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("vacclearapps:"))
async def confirm_clear_applications(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    vacancy = await database.get_vacancy(tenant_id, key)
    if not vacancy:
        await callback.answer("Bu vakansiya topilmadi.", show_alert=True)
        return

    stats_list = await database.get_vacancy_stats(tenant_id)
    stats = next((s for s in stats_list if s["vacancy_key"] == key), None)
    count = stats["total"] if stats else 0

    builder = InlineKeyboardBuilder()
    builder.button(text="⚠️ Ha, hammasini o'chirish", callback_data=f"vacclearappsconfirm:{key}")
    builder.button(text="Bekor qilish", callback_data=f"vacedit:{key}")
    builder.adjust(1)

    await callback.message.edit_text(
        f"<b>{vacancy['title']}</b> bo'yicha {count} ta arizani butunlay o'chirmoqchimisiz?\n\n"
        "⚠️ Bu amalni ortga qaytarib bo'lmaydi — statistika ham 0'dan boshlanadi. "
        "Vakansiyaning o'zi va savollari SAQLANIB QOLADI.\n\n"
        "Bu arizalarni topshirgan nomzodlar buni o'chirgach QAYTA ariza topshira oladi.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("vacclearappsconfirm:"))
async def clear_applications(callback: CallbackQuery, tenant_id: int):
    key = callback.data.split(":", 1)[1]
    deleted = await database.delete_applications_for_vacancy(tenant_id, key)
    await callback.answer(f"{deleted} ta ariza o'chirildi.", show_alert=True)
    await _show_edit_menu(callback, tenant_id, key)


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
