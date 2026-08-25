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
    builder.button(text="💡 Maslahatlar", callback_data="menu:tips")
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


_LEADS_PAGE_SIZE = 10


@router.callback_query(F.data.startswith("menu:leads"))
async def show_leads(callback: CallbackQuery, tenant: dict = None):
    # Ehtiyot chorasi: faqat asoschining o'z admin-boti orqali ruxsat —
    # tugma boshqalarga umuman ko'rsatilmaydi, lekin himoyani ikki marta
    # tekshirish zarar qilmaydi.
    if not _is_founder_tenant(tenant):
        await callback.answer("Ruxsat yo'q.", show_alert=True)
        return

    parts = callback.data.split(":")
    page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    total = await database.count_leads()
    leads = await database.list_leads(limit=_LEADS_PAGE_SIZE, offset=page * _LEADS_PAGE_SIZE)

    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Oldingi", callback_data=f"menu:leads:{page - 1}")
    if (page + 1) * _LEADS_PAGE_SIZE < total:
        builder.button(text="Keyingi ➡️", callback_data=f"menu:leads:{page + 1}")
    builder.button(text="🏠 Bosh menyu", callback_data="menu:main")
    builder.adjust(2, 1)

    if not leads:
        text = "🎯 <b>Lidlar</b>\n\nHozircha hech qanday lid yo'q." if page == 0 else "Boshqa lid yo'q."
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        await callback.answer()
        return

    total_pages = (total + _LEADS_PAGE_SIZE - 1) // _LEADS_PAGE_SIZE
    lines = [f"🎯 <b>Lidlar</b> — jami {total} ta (sahifa {page + 1}/{total_pages})", ""]
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


@router.callback_query(F.data == "menu:tips")
async def show_tips_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Vakansiya yaratish", callback_data="tips:vacancy")
    builder.button(text="❓ Savol turlari (filtr/AI/ovoz)", callback_data="tips:questions")
    builder.button(text="📅 Suhbat rejasi", callback_data="tips:interview")
    builder.button(text="📊 Statistika", callback_data="tips:stats")
    builder.button(text="⬅️ Bosh menyu", callback_data="menu:main")
    builder.adjust(1)
    await callback.message.edit_text("💡 <b>Maslahatlar</b>\n\nQaysi mavzu qiziqtiradi?", reply_markup=builder.as_markup())
    await callback.answer()


_TIPS = {
    "vacancy": (
        "➕ <b>Vakansiya yaratish</b>\n\n"
        "1. Bosh menyu → \"➕ Yangi vakansiya\"\n"
        "2. Lavozim nomini yozing (masalan: \"Sotuv menejeri\")\n"
        "3. Talablarni 1-2 gapda yozing (yoki o'tkazib yuboring)\n"
        "4. AI avtomatik savollar tuzadi — ko'rib chiqib saqlaysiz yoki o'zgartirasiz\n\n"
        "Har bir vakansiyani keyinchalik \"✏️ Tahrirlash\" orqali o'zgartirish, "
        "vaqtincha o'chirish yoki butunlay o'chirish mumkin."
    ),
    "questions": (
        "❓ <b>Savol turlari</b>\n\n"
        "🔒 <b>Filtr</b> — Ha/Yo'q savol. Salbiy javobda nomzod avtomatik rad etiladi.\n\n"
        "🤖 <b>AI tahlil</b> — javob chuqur tekshiriladi (fikr, reja, tajriba kabi savollar).\n\n"
        "🎙 <b>Ovozli (majburiy)</b> — nomzod OVOZ orqali javob beradi, audio to'g'ridan-to'g'ri "
        "sizga yuboriladi, o'zingiz tinglab baholaysiz. Ko'pi bilan 1-2 ta savolga qo'llang.\n\n"
        "⬜️ <b>Oddiy (belgisiz)</b> — faktik savol. Nomzod rezyume yuklasa, javob "
        "AVTOMATIK topilishi mumkin, qayta so'ralmaydi."
    ),
    "interview": (
        "📅 <b>Suhbat rejasi</b>\n\n"
        "\"📅 Suhbat vaqtlari\" bo'limida:\n"
        "• Bo'sh vaqt oralig'ini qo'shasiz\n"
        "• Qabul qilingan nomzod shu vaqtlardan birini tanlaydi\n\n"
        "\"⚙️ Sozlamalar\"da manzil, kim bilan suhbat bo'lishi va eslatma matnini "
        "bir marta kiritib qo'ysangiz, har safar avtomatik yuboriladi."
    ),
    "stats": (
        "📊 <b>Statistika</b>\n\n"
        "• Bugun/hafta/oy — necha ariza kelayotganini ko'rasiz\n"
        "• Nomzodlar sifati — AI qancha kuchli/o'rtacha/zaif deb topganini ko'rsatadi\n"
        "• Eng faol vakansiya — qaysi e'lon ko'proq ariza olayotganini ko'rsatadi\n\n"
        "Har bir vakansiyaning o'z sahifasida \"🏆 Eng yaxshi nomzodlar\" va "
        "\"📥 Excel yuklab olish\" ham bor."
    ),
}


@router.callback_query(F.data.startswith("tips:"))
async def show_tip_detail(callback: CallbackQuery):
    key = callback.data.split(":", 1)[1]
    text = _TIPS.get(key)
    if not text:
        await callback.answer()
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Orqaga", callback_data="menu:tips")
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "menu:stats")
async def show_stats(callback: CallbackQuery, tenant_id: int, tenant: dict = None):
    from services.plans import tenant_has_feature

    has_advanced = tenant_has_feature(tenant, "advanced_stats")
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
    ]

    if has_advanced:
        time_stats = await database.get_time_based_stats(tenant_id)
        lines.append(
            f"🗓 Bugun: <b>{time_stats['today']}</b> ta ariza | "
            f"Bu hafta: <b>{time_stats['week']}</b> | Bu oy: <b>{time_stats['month']}</b>"
        )
        lines.append("")

    lines += [
        f"⏳ Kutilmoqda: {overall['pending']}",
        f"✅ Qabul qilingan: {overall['accepted']}",
        f"❌ Rad etilgan (jami): {overall['rejected_total']}",
        f"   • Admin tomonidan: {overall['declined_by_admin']}",
        f"   • Talabga javob bermadi: {overall['rejected_hard_filter']}",
        f"   • Mavzuga mos kelmadi: {overall['rejected_irrelevant']}",
        f"   • AI orqali yozilgan deb topildi: {overall['rejected_ai_generated']}",
    ]

    if has_advanced:
        ai_stats = await database.get_ai_verdict_stats(tenant_id)
        if ai_stats["scored_total"]:
            vc = ai_stats["verdict_counts"]
            lines.append("")
            lines.append(
                f"🎯 <b>Nomzodlar sifati</b> (AI baholagan {ai_stats['scored_total']} ta, "
                f"o'rtacha ball: {ai_stats['avg_score']}/100)"
            )
            lines.append(f"   🟢 Kuchli: {vc['yashil']} | 🟡 O'rtacha: {vc['sariq']} | 🔴 Zaif: {vc['qizil']}")

        if per_vacancy:
            top = per_vacancy[0]
            lines.append("")
            lines.append(f"🔥 Eng faol vakansiya: <b>{top['vacancy_title']}</b> ({top['total']} ta ariza)")
    else:
        lines.append("")
        lines.append("💡 Trend, nomzodlar sifati va eng faol vakansiya — BUSINESS/PRO tarifida.")

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

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n\n…(qisqartirildi)"

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()
