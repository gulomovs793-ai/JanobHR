"""Admin bot — tarif tanlash (sinov/tarif tugagach yuboriladigan xabardagi
tugmalar), tavsifini ko'rsatish va to'lov ko'rsatmasi."""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services import database
from services.plans import PLANS, format_plan_detail

logger = logging.getLogger("janob_hr_bot")

router = Router(name="admin_billing")


@router.callback_query(F.data.startswith("billing:view:"))
async def view_plan(callback: CallbackQuery):
    plan_key = callback.data.split(":")[-1]
    plan = PLANS.get(plan_key)
    if not plan:
        await callback.answer("Noma'lum tarif.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    builder.button(text="💳 To'lov qilish", callback_data=f"billing:pay:{plan_key}")
    builder.button(text="⬅️ Orqaga", callback_data="billing:back")
    builder.adjust(1)

    await callback.message.edit_text(format_plan_detail(plan), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data == "billing:back")
async def back_to_plans(callback: CallbackQuery, tenant_id: int):
    from handlers.questions import _send_tariff_choices

    tenant = await database.get_tenant(tenant_id)
    if not tenant:
        await callback.answer("Xatolik yuz berdi.", show_alert=True)
        return

    await callback.message.delete()
    await _send_tariff_choices(tenant, reason="trial")
    await callback.answer()


@router.callback_query(F.data.startswith("billing:pay:"))
async def choose_plan(callback: CallbackQuery, tenant_id: int):
    from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER
    from services.payment_automation import create_payment_order

    plan_key = callback.data.split(":")[-1]
    plan = PLANS.get(plan_key)
    if not plan:
        await callback.answer("Noma'lum tarif.", show_alert=True)
        return

    tenant = await database.get_tenant(tenant_id)
    if not tenant or not tenant["admin_user_ids"]:
        await callback.answer("Xatolik yuz berdi.", show_alert=True)
        return

    if not PAYMENT_CARD_NUMBER:
        await callback.message.edit_text(
            f"{plan['name']} tanlandi. To'lov hozircha sozlanmagan — tez orada siz bilan bog'lanamiz."
        )
        await callback.answer()
        return

    order = await create_payment_order(
        tenant_id, base_amount=plan["price"],
        notify_bot_token=tenant["admin_bot_token"], notify_chat_id=tenant["admin_user_ids"][0],
        plan=plan_key,
    )
    card_digits = PAYMENT_CARD_NUMBER.replace(" ", "")

    await callback.message.edit_text(
        f"✅ {plan['name']} tanlandi.\n\n"
        f"💳 Karta: <code>{card_digits}</code>\n"
        f"👤 {PAYMENT_CARD_HOLDER}\n"
        f"💰 Summa: <code>{order['amount']}</code> so'm\n\n"
        f"⚠️ Aynan <code>{order['amount']}</code> so'm o'tkazing. To'lov tushishi bilan "
        "tarifingiz avtomatik faollashadi."
    )
    await callback.answer()
