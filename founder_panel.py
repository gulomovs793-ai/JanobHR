"""
Janob HR — "Bosh boshqaruv" boti. FAQAT `FOUNDER_USER_IDS`dagi shaxslar
ishlata oladi. Vazifasi: yangi (pending) mijozlarni ko'rib chiqish va
to'lov tasdiqlangach, bir tugma bilan faollashtirish — bu paytda ikkala
bot (nomzod + admin) uchun webhook avtomatik o'rnatiladi.
"""

import asyncio
import logging
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import (
    FOUNDER_BOT_TOKEN,
    FOUNDER_USER_IDS,
    PARTNER_BOT_TOKEN,
    WEBHOOK_BASE_URL,
)
from services import database
from services import partner_database as pdb
from services.plans import get_plan_transition

logger = logging.getLogger("janob_hr_founder")

router = Router(name="founder_panel")

FOUNDER_MENU = {
    "panel": "👑 Founder panel",
    "customers": "🏢 Mijozlar",
    "leads": "📞 Lidlar",
    "partners": "🤝 Hamkorlar uchun arizalar",
    "payments": "💳 To'lovlar",
    "renewals": "⏰ Uzaytirishlar",
    "stats": "📊 Statistika",
    "activate": "🔑 Tarifni qo'lda yoqish",
}


def _founder_services_keyboard() -> ReplyKeyboardMarkup:
    # Reply-keyboard WebApp buttons are opened as Telegram SimpleWebView and
    # do not reliably include user initData. Keep this as a normal text
    # button; its handler below returns an inline WebApp button, which does
    # include signed Telegram user data required by Founder auth.
    panel = KeyboardButton(text=FOUNDER_MENU["panel"])
    return ReplyKeyboardMarkup(
        keyboard=[
            [panel],
            [KeyboardButton(text=FOUNDER_MENU["customers"]), KeyboardButton(text=FOUNDER_MENU["leads"])],
            [KeyboardButton(text=FOUNDER_MENU["partners"])],
            [KeyboardButton(text=FOUNDER_MENU["payments"]), KeyboardButton(text=FOUNDER_MENU["renewals"])],
            [KeyboardButton(text=FOUNDER_MENU["stats"]), KeyboardButton(text=FOUNDER_MENU["activate"])],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Founder xizmatini tanlang",
    )


class FounderForm(StatesGroup):
    waiting_order_code = State()


_LEAD_STATUS = {
    "new": "🆕 Yangi",
    "contacted": "💬 Bog'lanildi",
    "demo": "🎯 Demo",
    "payment": "💳 To'lov kutilyapti",
    "customer": "✅ Mijoz bo'ldi",
    "lost": "❌ Rad etdi",
    "bot_created": "🤖 Bot yaratildi",
}


def _callback_int(data: str | None, prefix: str) -> int | None:
    """Parse a numeric callback payload without letting malformed input crash a handler."""
    value = (data or "")[len(prefix) :] if (data or "").startswith(prefix) else ""
    if not value.isdecimal() or len(value) > 10:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _tenant_summary(t: dict) -> str:
    username = t.get("contact_username")
    telegram_contact = f"@{escape(str(username))}" if username else "—"
    status_label = {
        "pending": "🔥 Yangi lead",
        "active": "🟢 Faol mijoz",
        "inactive": "⏸ To'xtatilgan",
    }.get(t["status"], t["status"])
    candidate_bot = f"@{escape(str(t['bot_username']))}" if t.get("bot_username") else "sozlanmoqda"
    admin_bot = (
        f"@{escape(str(t['admin_bot_username']))}"
        if t.get("admin_bot_username")
        else "sozlanmoqda"
    )
    created_at = escape(str(t.get("created_at") or "—")[:16].replace("T", " "))
    return (
        f"🏢 <b>№{t['id']} — {escape(str(t.get('company_name') or '—'))}</b>\n\n"
        f"👤 Mas'ul: {escape(str(t.get('contact_name') or '—'))}\n"
        f"📱 Telefon: <code>{escape(str(t.get('contact_phone') or '—'))}</code>\n"
        f"💬 Telegram: {telegram_contact}\n"
        f"📌 Holat: {escape(str(status_label))}\n\n"
        f"Nomzod-bot: {candidate_bot}\n"
        f"Admin-bot: {admin_bot}\n"
        f"🗓 Ro'yxatdan o'tgan: {created_at}"
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    await show_main_menu(message)


async def show_main_menu(message: Message):
    stats = await database.get_founder_stats()

    await message.answer(
        "👑 <b>Janob HR — Founder</b>\n\n"
        f"Oxirgi 30 kun: <b>{stats['monthly_applications']} ta ariza</b>\n"
        f"Jami faol biznes: <b>{stats['active']} ta</b>\n\n"
        f"Bugungi yangi lidlar: <b>{stats['today_leads']} ta</b>\n"
        f"To'lov kutilyapti: <b>{stats['awaiting_payments']} ta</b>   ·   "
        f"5 kunda tugaydi: <b>{stats['expiring_soon']} ta</b>\n"
        f"30 kunlik tushum: <b>{stats['monthly_revenue']:,} so'm</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=_founder_services_keyboard(),
    )


async def _send_founder_tenants(message: Message):
    tenants = await database.list_tenants()
    builder = InlineKeyboardBuilder()
    for tenant in tenants[:50]:
        marker = {"active": "🟢", "pending": "🟠", "inactive": "🔴"}.get(tenant["status"], "•")
        builder.button(
            text=f"{marker} {tenant['company_name']}", callback_data=f"fp:view:{tenant['id']}"
        )
    builder.adjust(1)
    await message.answer(
        f"🏢 <b>Barcha mijozlar</b>\n\nJami: <b>{len(tenants)}</b>",
        reply_markup=builder.as_markup(),
    )


@router.message(F.text == FOUNDER_MENU["panel"])
async def service_founder_panel(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    builder = InlineKeyboardBuilder()
    if WEBHOOK_BASE_URL:
        builder.button(
            text="👑 Founder panelni ochish",
            web_app=WebAppInfo(url=f"{WEBHOOK_BASE_URL.rstrip('/')}/founder"),
        )
    await message.answer(
        "Founder panelni xavfsiz ochish uchun quyidagi tugmani bosing:",
        reply_markup=builder.as_markup(),
    )


@router.message(F.text == FOUNDER_MENU["customers"])
async def service_founder_customers(message: Message):
    if message.from_user.id in FOUNDER_USER_IDS:
        await _send_founder_tenants(message)


@router.message(F.text == FOUNDER_MENU["leads"])
async def service_founder_leads(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    leads = await database.list_business_leads()
    builder = InlineKeyboardBuilder()
    for lead in leads[:50]:
        builder.button(
            text=f"{lead.get('company_name') or 'Kompaniya'} · {lead['contact_phone']}",
            callback_data=f"fp:lead:{lead['id']}",
        )
    builder.adjust(1)
    await message.answer(f"📞 <b>Lidlar</b>\n\nJami: <b>{len(leads)}</b>", reply_markup=builder.as_markup())


def _partner_review_keyboard(partner_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Tasdiqlash", callback_data=f"fp:partnerapprove:{partner_id}")
    builder.button(text="❌ Rad etish", callback_data=f"fp:partnerreject:{partner_id}")
    builder.button(text="⬅️ Arizalar", callback_data="fp:partners")
    builder.adjust(2, 1)
    return builder.as_markup()


async def _send_partner_applications(message: Message):
    partners = await pdb.list_partners(status="pending", limit=100)
    builder = InlineKeyboardBuilder()
    for partner in partners:
        role = partner.get("role") or "boshqa"
        builder.button(
            text=f"#{partner['id']} · {partner.get('full_name') or 'Hamkor'} · {role}",
            callback_data=f"fp:partner:{partner['id']}",
        )
    builder.button(text="⬅️ Bosh menyu", callback_data="fp:main")
    builder.adjust(1)
    text = (
        f"🤝 <b>Hamkorlik uchun arizalar</b>\n\nKutilmoqda: <b>{len(partners)}</b>"
        if partners
        else "🤝 <b>Hamkorlik uchun arizalar</b>\n\nHozircha yangi ariza yo'q."
    )
    await message.answer(text, reply_markup=builder.as_markup())


@router.message(F.text == FOUNDER_MENU["partners"])
async def service_founder_partners(message: Message):
    if message.from_user.id in FOUNDER_USER_IDS:
        await _send_partner_applications(message)


@router.callback_query(F.data == "fp:partners")
async def list_partner_applications(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    partners = await pdb.list_partners(status="pending", limit=100)
    builder = InlineKeyboardBuilder()
    for partner in partners:
        builder.button(
            text=f"#{partner['id']} · {partner.get('full_name') or 'Hamkor'}",
            callback_data=f"fp:partner:{partner['id']}",
        )
    builder.button(text="⬅️ Bosh menyu", callback_data="fp:main")
    builder.adjust(1)
    text = (
        f"🤝 <b>Hamkorlik uchun arizalar</b>\n\nKutilmoqda: <b>{len(partners)}</b>"
        if partners
        else "🤝 <b>Hamkorlik uchun arizalar</b>\n\nHozircha yangi ariza yo'q."
    )
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("fp:partner:"))
async def view_partner_application(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    partner_id = _callback_int(callback.data, "fp:partner:")
    if partner_id is None:
        await callback.answer("Ariza identifikatori noto'g'ri.", show_alert=True)
        return
    partner = await pdb.get_partner(partner_id)
    if not partner:
        await callback.answer("Hamkor arizasi topilmadi.", show_alert=True)
        return
    business_clients = "Ha" if partner.get("has_business_clients") else "Yo'q"
    status = {"pending": "⏳ Kutilmoqda", "approved": "✅ Tasdiqlangan", "rejected": "❌ Rad etilgan"}.get(
        partner.get("status"), partner.get("status") or "—"
    )
    back_builder = InlineKeyboardBuilder()
    if partner.get("status") == "pending":
        markup = _partner_review_keyboard(partner["id"])
    else:
        back_builder.button(text="⬅️ Arizalar", callback_data="fp:partners")
        markup = back_builder.as_markup()
    await callback.message.edit_text(
        f"🤝 <b>Hamkor arizasi #{partner['id']}</b>\n\n"
        f"👤 Ism: <b>{escape(str(partner.get('full_name') or '—'))}</b>\n"
        f"💬 Telegram: @{escape(str(partner.get('username') or '—'))}\n"
        f"📱 Telefon: <code>{escape(str(partner.get('phone') or '—'))}</code>\n"
        f"🎯 Yo'nalish: {escape(str(partner.get('role') or '—'))}\n"
        f"🏢 Biznes mijozlari: {business_clients}\n"
        f"📊 Segment: {escape(str(partner.get('client_band') or '—'))}\n"
        f"📌 Holat: <b>{escape(str(status))}</b>",
        reply_markup=markup,
    )
    await callback.answer()


async def _set_partner_application_status(callback: CallbackQuery, status: str):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    partner_id = _callback_int(callback.data, "fp:partnerapprove:")
    if partner_id is None:
        partner_id = _callback_int(callback.data, "fp:partnerreject:")
    if partner_id is None:
        partner_id = _callback_int(callback.data, "partner_approve:")
    if partner_id is None:
        partner_id = _callback_int(callback.data, "partner_reject:")
    if partner_id is None:
        await callback.answer("Ariza identifikatori noto'g'ri.", show_alert=True)
        return
    partner = await pdb.set_partner_status(
        partner_id, status, expected_status="pending"
    )
    if not partner:
        await callback.answer("Hamkor arizasi topilmadi.", show_alert=True)
        return
    await callback.message.edit_text(
        f"{'✅ Tasdiqlandi' if status == 'approved' else '❌ Rad etildi'}: "
        f"<b>{escape(str(partner.get('full_name') or 'Hamkor'))}</b> (#{partner_id})"
    )
    # Ariza Founder Botda ko'riladi, lekin javob partnerning o'zi ochgan
    # Partner Bot chatiga borishi kerak. Founder Botdan yuborilsa, partner
    # u bot bilan hech qachon suhbat boshlamagan bo'lishi mumkin va xabar
    # yetib bormaydi; reply keyboard ham noto'g'ri botda qolib ketadi.
    if not PARTNER_BOT_TOKEN:
        logger.error("Partner status notification yuborilmadi: PARTNER_BOT_TOKEN sozlanmagan.")
    else:
        partner_bot = Bot(
            token=PARTNER_BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            if status == "approved":
                from partner_bot import main_menu

                await partner_bot.send_message(
                    partner["telegram_user_id"],
                    "🎉 <b>Hamkorligingiz tasdiqlandi!</b>\n\n"
                    "Sizga referral link, promo kod, leadlar va komissiya paneli ochildi.",
                    reply_markup=main_menu(),
                )
            else:
                await partner_bot.send_message(
                    partner["telegram_user_id"],
                    "Arizangiz hozircha tasdiqlanmadi. Keyinroq /start orqali qayta topshirishingiz mumkin.",
                )
        except Exception:
            logger.exception(
                "Partner status notification yuborilmadi: partner_id=%s status=%s",
                partner_id,
                status,
            )
        finally:
            await partner_bot.session.close()
    await callback.answer("Saqlandi")


@router.callback_query(F.data.startswith("fp:partnerapprove:"))
@router.callback_query(F.data.startswith("partner_approve:"))
async def approve_partner_application(callback: CallbackQuery):
    await _set_partner_application_status(callback, "approved")


@router.callback_query(F.data.startswith("fp:partnerreject:"))
@router.callback_query(F.data.startswith("partner_reject:"))
async def reject_partner_application(callback: CallbackQuery):
    await _set_partner_application_status(callback, "rejected")


@router.message(F.text.in_({FOUNDER_MENU["payments"], FOUNDER_MENU["renewals"]}))
async def service_founder_live_section(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    builder = InlineKeyboardBuilder()
    if WEBHOOK_BASE_URL:
        builder.button(
            text="👑 Founder panelni ochish",
            web_app=WebAppInfo(url=f"{WEBHOOK_BASE_URL.rstrip('/')}/founder"),
        )
    await message.answer(
        "To'lovlar va uzaytirishlar jonli Founder panelda ko'rsatiladi.",
        reply_markup=builder.as_markup(),
    )


@router.message(F.text == FOUNDER_MENU["stats"])
async def service_founder_stats(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    stats = await database.get_founder_stats()
    await message.answer(
        "📊 <b>Janob HR statistikasi</b>\n\n"
        f"Faol mijozlar: <b>{stats['active']}</b>\n"
        f"Yangi lidlar: <b>{stats['business_leads']}</b>\n"
        f"To'lov kutilyapti: <b>{stats['awaiting_payments']}</b>\n"
        f"Uzaytirish kerak: <b>{stats['expiring_soon']}</b>\n"
        f"30 kunlik tushum: <b>{stats['monthly_revenue']:,} so'm</b>"
    )


@router.message(F.text == FOUNDER_MENU["activate"])
async def service_founder_activate(message: Message, state: FSMContext):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    await message.answer(
        "Mijoz yuborgan buyurtma raqamini jo'nating. Masalan: <code>JH-XXXXXX</code>"
    )
    await state.set_state(FounderForm.waiting_order_code)


@router.callback_query(F.data == "fp:main")
async def back_to_main(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data == "fp:pending")
async def list_pending(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenants = await database.list_tenants(status="pending")
    builder = InlineKeyboardBuilder()
    if not tenants:
        text = "⏳ Hozircha kutilayotgan mijoz yo'q."
    else:
        text = "⏳ <b>Faollashtirishni kutayotgan mijozlar:</b>"
        for t in tenants:
            phone = t.get("contact_phone") or "raqam yo'q"
            builder.button(
                text=f"№{t['id']} · {t['company_name']} · {phone}",
                callback_data=f"fp:view:{t['id']}",
            )
    builder.button(text="⬅️ Orqaga", callback_data="fp:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "fp:leads")
async def list_leads(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    leads = await database.list_business_leads()
    builder = InlineKeyboardBuilder()
    text = (
        "📞 <b>Biznes lidlar</b>\n\nRaqam va ma'lumotni ko'rish uchun lidni tanlang:"
        if leads
        else "Hozircha biznes lid yo'q."
    )
    for lead in leads[:50]:
        builder.button(
            text=f"#{lead['id']} · {lead.get('company_name') or 'Kompaniya'} · {lead['contact_phone']}",
            callback_data=f"fp:lead:{lead['id']}",
        )
    builder.button(text="⬅️ Bosh menyu", callback_data="fp:main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("fp:lead:"))
async def view_lead(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    lead_id = _callback_int(callback.data, "fp:lead:")
    if lead_id is None:
        await callback.answer("Lid identifikatori noto'g'ri.", show_alert=True)
        return
    lead = await database.get_business_lead(lead_id)
    if not lead:
        await callback.answer("Lid topilmadi.", show_alert=True)
        return
    username = lead.get("contact_username") or ""
    builder = InlineKeyboardBuilder()
    if username:
        builder.button(text="💬 Telegram'da yozish", url=f"https://t.me/{username}")
    builder.button(
        text="🔄 Holatini o'zgartirish", callback_data=f"fp:leadstatus:{lead['id']}"
    )
    builder.button(text="⬅️ Lidlar", callback_data="fp:leads")
    builder.adjust(1)
    await callback.message.edit_text(
        f"📞 <b>Lid #{lead['id']} — {escape(str(lead.get('company_name') or '—'))}</b>\n\n"
        f"👤 {escape(str(lead.get('contact_name') or '—'))}\n"
        f"📱 <code>{escape(str(lead.get('contact_phone') or '—'))}</code>\n"
        f"💬 @{escape(str(username or '—'))}\n\n"
        f"Muammo: {escape(str(lead.get('hiring_problem') or '—'))}\n"
        f"Hozirgi jarayon: {escape(str(lead.get('current_process') or '—'))}\n"
        f"Kerakli natija: {escape(str(lead.get('desired_result') or '—'))}\n\n"
        f"Holat: <b>{escape(str(_LEAD_STATUS.get(lead['status'], lead['status'])))}</b>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fp:leadstatus:"))
async def choose_lead_status(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    lead_id = _callback_int(callback.data, "fp:leadstatus:")
    if lead_id is None:
        await callback.answer("Lid identifikatori noto'g'ri.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    for code, label in _LEAD_STATUS.items():
        builder.button(text=label, callback_data=f"fp:setlead:{lead_id}:{code}")
    builder.button(text="⬅️ Lidga qaytish", callback_data=f"fp:lead:{lead_id}")
    builder.adjust(2, 2, 2, 1, 1)
    await callback.message.edit_text(
        "Lidning yangi holatini tanlang:", reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fp:setlead:"))
async def set_lead_status(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or parts[0] != "fp" or parts[1] != "setlead":
        await callback.answer("Lid holati so'rovi noto'g'ri.", show_alert=True)
        return
    lead_id, status = parts[2], parts[3]
    if not lead_id.isdecimal() or status not in _LEAD_STATUS:
        await callback.answer("Lid holati so'rovi noto'g'ri.", show_alert=True)
        return
    if not await database.update_business_lead_status(int(lead_id), status):
        await callback.answer("Holatni saqlab bo'lmadi.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Lidga qaytish", callback_data=f"fp:lead:{lead_id}")
    await callback.message.edit_text(
        f"✅ Holat saqlandi: <b>{escape(str(_LEAD_STATUS.get(status, status)))}</b>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data == "fp:manual_payment")
async def manual_payment_help(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    await callback.message.edit_text(
        "🔑 <b>Tarifni qo'lda yoqish</b>\n\n"
        "Mijoz yuborgan buyurtma raqamini jo'nating. Masalan:\n"
        "<code>JH-XXXXXX</code>\n\n"
        "Bot buyurtmani topib, tegishli mijoz tarifini o'zi yoqadi."
    )
    await state.set_state(FounderForm.waiting_order_code)
    await callback.answer()


async def _activate_order(message: Message, code: str, state: FSMContext | None = None):
    order = await database.get_payment_order_by_code(code)
    if not order:
        await message.answer(f"❌ <code>{escape(str(code))}</code> buyurtmasi topilmadi.")
        return
    if order["status"] == "approved" and order.get("subscription_activated_at"):
        await message.answer(
            f"✅ <code>{escape(str(code))}</code> avval tasdiqlangan. Tarif qayta uzaytirilmadi."
        )
        return
    if order["status"] not in {"awaiting_payment", "needs_review", "approved"}:
        await message.answer(
            f"⚠️ Bu buyurtmani yoqib bo'lmaydi. Holati: <b>{escape(str(order['status']))}</b>"
        )
        return
    usage = await database.get_subscription_usage(order["tenant_id"])
    if get_plan_transition(
        usage["plan"].code,
        order.get("plan_code", "start"),
        current_expired=usage["expired"],
    ) == "blocked":
        await message.answer(
            f"⛔ <b>Past tarifni yoqib bo'lmaydi.</b>\n\n"
            f"Mijozda <b>{usage['plan'].name}</b> tarifi hali faol. "
            "Muddati tugagach past tarifni tanlash mumkin. To'lovni qo'lda tekshiring."
        )
        return
    won = order["status"] == "approved"
    if not won:
        won = await database.approve_payment_order_manually(order["id"])
        if not won:
            await message.answer("Buyurtma holati o'zgargan. Qayta tekshiring.")
            return
    from services.tenant_activation import activate_tenant as do_activate

    result = await do_activate(order["tenant_id"])
    if not result.get("ok"):
        await database.mark_payment_order_needs_review(
            order["id"], "manual activation failed", keep_approved=True
        )
        await message.answer(
            f"⚠️ To'lov topildi, lekin botni yoqishda xato: {escape(str(result.get('error') or 'nomaʼlum xato'))}"
        )
        return
    try:
        activation_record = await database.activate_subscription_for_order(order["id"])
        if not activation_record.get("ok"):
            raise RuntimeError("Tarifni atomik faollashtirish amalga oshmadi")
    except Exception as exc:
        # Keep old standalone integrations usable when they provide a mocked
        # order without the core payment schema. A real webhook startup always
        # runs init_db first, so production never takes this compatibility path.
        if "no such table" in str(exc).lower() and order.get("tenant_id"):
            await database.activate_subscription(
                order["tenant_id"],
                order.get("plan_code", "start"),
                order.get("billing_months", 1),
            )
        else:
            await database.mark_payment_order_needs_review(
                order["id"], str(exc)[:500], keep_approved=True
            )
            await message.answer(
                "⚠️ To'lov tasdiqlandi, lekin tarifni bir martalik yoqishda xato. "
                "Recovery qayta urinadi yoki qayta tekshiring."
            )
            logger.exception("Manual order activation failed: %s", code)
            return
    partner_sale = None
    for attempt in range(3):
        try:
            partner_sale = await pdb.finalize_sale_for_order(
                order["id"], actual_amount=order["amount"]
            )
            if partner_sale:
                break
        except Exception:
            logger.exception(
                "Qo'lda tasdiqlangan payment uchun partner komissiyasi yozilmadi: %s attempt=%s",
                code,
                attempt + 1,
            )
            if attempt < 2:
                await asyncio.sleep(0.2)
    tenant = await database.get_tenant(order["tenant_id"])
    if tenant and tenant.get("admin_bot_token") and tenant.get("admin_user_ids"):
        customer_bot = Bot(token=tenant["admin_bot_token"])
        notified = False
        try:
            for admin_id in tenant["admin_user_ids"]:
                try:
                    await customer_bot.send_message(
                        admin_id,
                        "✅ <b>TO'LOV QABUL QILINDI</b>\n\n"
                        f"Buyurtma: <code>{code}</code>\n"
                        f"Summa: <b>{order['amount']:,} so'm</b>\n\n"
                        "Tarifingiz yoqildi. Janob HR'dan foydalanishingiz mumkin.",
                        parse_mode=ParseMode.HTML,
                    )
                    notified = True
                except Exception:
                    logger.exception(
                        "Qo'lda yoqilgan tarif tasdig'i mijoz adminiga yuborilmadi: %s",
                        admin_id,
                    )
            if notified:
                await database.mark_customer_payment_notified(code)
        except Exception:
            logger.exception(
                "Qo'lda yoqilgan tarif tasdig'i mijozga yuborilmadi: %s", code
            )
        finally:
            await customer_bot.session.close()
    await message.answer(
        f"✅ <b>Tarif qo'lda yoqildi</b>\n\n"
        f"Buyurtma: <code>{code}</code>\n"
        f"Mijoz №{order['tenant_id']}\n"
        f"Summa: <b>{order['amount']:,} so'm</b>"
        + (
            f"\nPartner komissiyasi: <b>{pdb.format_uzs(partner_sale['commission_amount'])}</b>"
            if partner_sale
            else ""
        )
    )
    if state:
        await state.clear()


@router.message(FounderForm.waiting_order_code, F.text)
async def manual_activate_from_button(message: Message, state: FSMContext):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    code = (message.text or "").strip().upper()
    if not code.startswith("JH-"):
        await message.answer(
            "Buyurtma raqami <code>JH-</code> bilan boshlanadi. Qayta yuboring."
        )
        return
    await _activate_order(message, code, state)


@router.message(Command("activate"))
async def manual_activate_payment(message: Message, state: FSMContext):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer(
            "Buyurtma raqamini yozing: <code>/activate JH-XXXXXX</code>"
        )
        return
    await _activate_order(message, parts[1].strip().upper(), state)


@router.callback_query(F.data == "fp:active")
async def list_active(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenants = await database.list_tenants(status="active")
    builder = InlineKeyboardBuilder()
    if not tenants:
        text = "✅ Hozircha faol mijoz yo'q."
    else:
        text = "✅ <b>Faol mijozlar:</b>"
        for t in tenants:
            phone = t.get("contact_phone") or "raqam yo'q"
            builder.button(
                text=f"№{t['id']} · {t['company_name']} · {phone}",
                callback_data=f"fp:view:{t['id']}",
            )
    builder.button(text="⬅️ Orqaga", callback_data="fp:main")
    builder.adjust(1)

    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "fp:inactive")
async def list_inactive(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    tenants = await database.list_tenants(status="inactive")
    builder = InlineKeyboardBuilder()
    text = "⏸ <b>To'xtatilgan mijozlar:</b>" if tenants else "To'xtatilgan mijoz yo'q."
    for t in tenants:
        phone = t.get("contact_phone") or "raqam yo'q"
        builder.button(
            text=f"№{t['id']} · {t['company_name']} · {phone}",
            callback_data=f"fp:view:{t['id']}",
        )
    builder.button(text="⬅️ Bosh menyu", callback_data="fp:main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "fp:stats")
async def show_business_stats(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    stats = await database.get_founder_stats()
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Bosh menyu", callback_data="fp:main")
    await callback.message.edit_text(
        "📊 <b>Janob HR biznes ko'rsatkichlari</b>\n\n"
        f"🔥 Yangi leadlar: <b>{stats['pending']}</b>\n"
        f"💼 Faol mijozlar: <b>{stats['active']}</b>\n"
        f"⏸ To'xtatilgan: <b>{stats['inactive']}</b>\n\n"
        f"📞 Jami biznes lidlar: <b>{stats['business_leads']}</b>\n"
        f"🆕 Bugungi yangi lidlar: <b>{stats['today_leads']}</b>\n"
        f"💳 To'lov kutayotganlar: <b>{stats['awaiting_payments']}</b>\n"
        f"⏰ 5 kunda tarifi tugaydi: <b>{stats['expiring_soon']}</b>\n"
        f"💰 30 kunlik tushum: <b>{stats['monthly_revenue']:,} so'm</b>\n\n"
        f"📥 Oxirgi 30 kun arizalari: <b>{stats['monthly_applications']}</b>\n"
        f"🗂 Jami arizalar: <b>{stats['total_applications']}</b>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fp:view:"))
async def view_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = _callback_int(callback.data, "fp:view:")
    if tenant_id is None:
        await callback.answer("Mijoz identifikatori noto'g'ri.", show_alert=True)
        return
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        await callback.answer("Bu mijoz topilmadi.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    if tenant.get("contact_username"):
        builder.button(
            text="💬 Telegram'da yozish",
            url=f"https://t.me/{tenant['contact_username']}",
        )
    if tenant["status"] == "pending":
        builder.button(
            text="✅ Faollashtirish", callback_data=f"fp:activate:{tenant_id}"
        )
    elif tenant["status"] == "active":
        builder.button(text="🔴 To'xtatish", callback_data=f"fp:deactivate:{tenant_id}")
    elif tenant["status"] == "inactive":
        builder.button(
            text="🟢 Qayta faollashtirish", callback_data=f"fp:activate:{tenant_id}"
        )
    builder.button(text="⬅️ Orqaga", callback_data="fp:main")
    builder.adjust(1)

    await callback.message.edit_text(
        _tenant_summary(tenant), reply_markup=builder.as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fp:activate:"))
async def activate_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = _callback_int(callback.data, "fp:activate:")
    if tenant_id is None:
        await callback.answer("Mijoz identifikatori noto'g'ri.", show_alert=True)
        return
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        await callback.answer("Bu mijoz topilmadi.", show_alert=True)
        return

    from services.tenant_activation import activate_tenant as do_activate

    await callback.answer("Faollashtirilmoqda...")
    result = await do_activate(tenant_id)

    if not result["ok"]:
        await callback.message.answer(
            f"⚠️ {escape(str(result.get('error') or 'Faollashtirish amalga oshmadi.'))}"
        )
        return

    await callback.message.edit_text(
        f"✅ <b>№{tenant_id} — {escape(str(tenant.get('company_name') or '—'))}</b> faollashtirildi!\n\n"
        f"Nomzod-bot: @{escape(str(result.get('candidate_username') or '—'))}\nAdmin-bot: @{escape(str(result.get('admin_username') or '—'))}\n\n"
        "Ikkala bot ham endi jonli ishlamoqda."
    )


@router.callback_query(F.data.startswith("fp:deactivate:"))
async def deactivate_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = _callback_int(callback.data, "fp:deactivate:")
    if tenant_id is None:
        await callback.answer("Mijoz identifikatori noto'g'ri.", show_alert=True)
        return
    if not await database.update_tenant_status(tenant_id, "inactive"):
        await callback.answer("Mijoz topilmadi yoki holati o'zgargan.", show_alert=True)
        return
    await callback.answer("Mijoz to'xtatildi.", show_alert=True)
    await list_active(callback)


async def main():
    if not FOUNDER_BOT_TOKEN:
        raise RuntimeError("FOUNDER_BOT_TOKEN topilmadi.")
    if WEBHOOK_BASE_URL:
        raise RuntimeError(
            "Founder Bot webhook_app.py ichida ishlaydi. WEBHOOK_BASE_URL sozlangan "
            "muhitda founder_panel.py ni alohida ishga tushirmang."
        )

    await database.init_db()
    bot = Bot(
        token=FOUNDER_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=False)
    logger.info("Janob HR Bosh boshqaruv boti ishga tushdi ✅")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
