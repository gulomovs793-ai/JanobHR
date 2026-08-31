"""
Janob HR — "Bosh boshqaruv" boti. FAQAT `FOUNDER_USER_IDS`dagi shaxslar
ishlata oladi. Vazifasi: yangi (pending) mijozlarni ko'rib chiqish va
to'lov tasdiqlangach, bir tugma bilan faollashtirish — bu paytda ikkala
bot (nomzod + admin) uchun webhook avtomatik o'rnatiladi.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS, WEBHOOK_BASE_URL
from services import database

logger = logging.getLogger("janob_hr_founder")

router = Router(name="founder_panel")


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


def _tenant_summary(t: dict) -> str:
    username = t.get("contact_username")
    telegram_contact = f"@{username}" if username else "—"
    status_label = {
        "pending": "🔥 Yangi lead",
        "active": "🟢 Faol mijoz",
        "inactive": "⏸ To'xtatilgan",
    }.get(t["status"], t["status"])
    candidate_bot = f"@{t['bot_username']}" if t.get("bot_username") else "sozlanmoqda"
    admin_bot = (
        f"@{t['admin_bot_username']}" if t.get("admin_bot_username") else "sozlanmoqda"
    )
    return (
        f"🏢 <b>№{t['id']} — {t['company_name']}</b>\n\n"
        f"👤 Mas'ul: {t.get('contact_name') or '—'}\n"
        f"📱 Telefon: <code>{t.get('contact_phone') or '—'}</code>\n"
        f"💬 Telegram: {telegram_contact}\n"
        f"📌 Holat: {status_label}\n\n"
        f"Nomzod-bot: {candidate_bot}\n"
        f"Admin-bot: {admin_bot}\n"
        f"🗓 Ro'yxatdan o'tgan: {t['created_at'][:16].replace('T', ' ')}"
    )


@router.message(CommandStart())
async def cmd_start(message: Message):
    if message.from_user.id not in FOUNDER_USER_IDS:
        return
    await show_main_menu(message)


async def show_main_menu(message: Message):
    stats = await database.get_founder_stats()

    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"🔥 Yangi leadlar ({stats['pending']})", callback_data="fp:pending"
    )
    builder.button(
        text=f"📞 Lidlar ({stats['business_leads']})", callback_data="fp:leads"
    )
    builder.button(
        text=f"💼 Faol mijozlar ({stats['active']})", callback_data="fp:active"
    )
    builder.button(
        text=f"⏸ To'xtatilgan ({stats['inactive']})", callback_data="fp:inactive"
    )
    builder.button(text="📊 Biznes ko'rsatkichlari", callback_data="fp:stats")
    builder.button(text="🔑 Tarifni qo'lda yoqish", callback_data="fp:manual_payment")
    builder.adjust(2, 2, 1)

    await message.answer(
        "👑 <b>Janob HR — Founder</b>\n\n"
        f"Oxirgi 30 kun: <b>{stats['monthly_applications']} ta ariza</b>\n"
        f"Jami faol biznes: <b>{stats['active']} ta</b>\n\n"
        f"To'lov kutilyapti: <b>{stats['awaiting_payments']} ta</b>   ·   "
        f"5 kunda tugaydi: <b>{stats['expiring_soon']} ta</b>\n"
        f"30 kunlik tushum: <b>{stats['monthly_revenue']:,} so'm</b>\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=builder.as_markup(),
    )


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
    lead = await database.get_business_lead(int(callback.data.rsplit(":", 1)[1]))
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
        f"📞 <b>Lid #{lead['id']} — {lead.get('company_name') or '—'}</b>\n\n"
        f"👤 {lead.get('contact_name') or '—'}\n"
        f"📱 <code>{lead['contact_phone']}</code>\n"
        f"💬 @{username or '—'}\n\n"
        f"Muammo: {lead.get('hiring_problem') or '—'}\n"
        f"Hozirgi jarayon: {lead.get('current_process') or '—'}\n"
        f"Kerakli natija: {lead.get('desired_result') or '—'}\n\n"
        f"Holat: <b>{_LEAD_STATUS.get(lead['status'], lead['status'])}</b>",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fp:leadstatus:"))
async def choose_lead_status(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return
    lead_id = int(callback.data.rsplit(":", 1)[1])
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
    _, _, lead_id, status = callback.data.split(":")
    if not await database.update_business_lead_status(int(lead_id), status):
        await callback.answer("Holatni saqlab bo'lmadi.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Lidga qaytish", callback_data=f"fp:lead:{lead_id}")
    await callback.message.edit_text(
        f"✅ Holat saqlandi: <b>{_LEAD_STATUS.get(status, status)}</b>",
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
        await message.answer(f"❌ <code>{code}</code> buyurtmasi topilmadi.")
        return
    if order["status"] == "approved":
        await message.answer(
            f"✅ <code>{code}</code> avval tasdiqlangan. Tarif qayta uzaytirilmadi."
        )
        return
    if order["status"] not in {"awaiting_payment", "needs_review"}:
        await message.answer(
            f"⚠️ Bu buyurtmani yoqib bo'lmaydi. Holati: <b>{order['status']}</b>"
        )
        return
    won = await database.approve_payment_order_manually(order["id"])
    if not won:
        await message.answer("Buyurtma holati o'zgargan. Qayta tekshiring.")
        return
    from services.tenant_activation import activate_tenant as do_activate

    result = await do_activate(order["tenant_id"])
    if not result.get("ok"):
        await database.mark_payment_order_needs_review(
            order["id"], "manual activation failed"
        )
        await message.answer(
            f"⚠️ To'lov topildi, lekin botni yoqishda xato: {result.get('error')}"
        )
        return
    await database.activate_subscription(
        order["tenant_id"],
        order.get("plan_code", "start"),
        order.get("billing_months", 1),
    )
    tenant = await database.get_tenant(order["tenant_id"])
    if tenant and tenant.get("admin_bot_token") and tenant.get("admin_user_ids"):
        customer_bot = Bot(token=tenant["admin_bot_token"])
        try:
            await customer_bot.send_message(
                tenant["admin_user_ids"][0],
                "✅ <b>TO'LOV QABUL QILINDI</b>\n\n"
                f"Buyurtma: <code>{code}</code>\n"
                f"Summa: <b>{order['amount']:,} so'm</b>\n\n"
                "Tarifingiz yoqildi. Janob HR'dan foydalanishingiz mumkin.",
            )
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

    tenant_id = int(callback.data.split(":")[2])
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

    tenant_id = int(callback.data.split(":")[2])
    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        await callback.answer("Bu mijoz topilmadi.", show_alert=True)
        return

    from services.tenant_activation import activate_tenant as do_activate

    await callback.answer("Faollashtirilmoqda...")
    result = await do_activate(tenant_id)

    if not result["ok"]:
        await callback.message.answer(f"⚠️ {result['error']}")
        return

    await callback.message.edit_text(
        f"✅ <b>№{tenant_id} — {tenant['company_name']}</b> faollashtirildi!\n\n"
        f"Nomzod-bot: @{result['candidate_username']}\nAdmin-bot: @{result['admin_username']}\n\n"
        "Ikkala bot ham endi jonli ishlamoqda."
    )


@router.callback_query(F.data.startswith("fp:deactivate:"))
async def deactivate_tenant(callback: CallbackQuery):
    if callback.from_user.id not in FOUNDER_USER_IDS:
        return

    tenant_id = int(callback.data.split(":")[2])
    await database.update_tenant_status(tenant_id, "inactive")
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
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Janob HR Bosh boshqaruv boti ishga tushdi ✅")
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(main())
