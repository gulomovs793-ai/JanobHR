"""Admin bot ichidagi tarif, limit va to'lov oynasi."""

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER
from services import database
from services.payment_automation import create_payment_order
from services.plans import PUBLIC_PLAN_CODES, format_som, get_plan

router = Router(name="admin_billing")


def _usage(value: int, limit: int | None) -> str:
    return f"{value} / {limit}" if limit is not None else f"{value} / ∞"


async def _show(callback: CallbackQuery, tenant_id: int) -> None:
    usage = await database.get_subscription_usage(tenant_id)
    plan = usage["plan"]
    expiry = (usage["expires_at"] or "—")[:10]
    text = (
        "💳 <b>Tarif va limitlar</b>\n\n"
        f"Joriy tarif: <b>{plan.name}</b>\n"
        f"Arizalar: <b>{_usage(usage['applications_used'], plan.application_limit)}</b>\n"
        f"Faol vakansiyalar: <b>{_usage(usage['vacancies_used'], plan.vacancy_limit)}</b>\n"
        f"Amal qilish sanasi: <b>{expiry}</b>\n\n"
        "Oylik tarifni tanlang:"
    )
    builder = InlineKeyboardBuilder()
    for code in PUBLIC_PLAN_CODES:
        item = get_plan(code)
        suffix = " · ommabop" if code == "growth" else ""
        builder.button(
            text=f"{item.name} — {format_som(item.price)}{suffix}",
            callback_data=f"billing:buy:{code}",
        )
    builder.button(text="⬅️ Bosh menyu", callback_data="menu:main")
    builder.adjust(1)
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "menu:billing")
async def billing_home(callback: CallbackQuery, tenant_id: int):
    await _show(callback, tenant_id)
    await callback.answer()


@router.callback_query(F.data.startswith("billing:buy:"))
async def billing_buy(callback: CallbackQuery, tenant_id: int):
    code = callback.data.rsplit(":", 1)[1]
    if code not in PUBLIC_PLAN_CODES:
        await callback.answer("Tarif topilmadi.", show_alert=True)
        return
    if not PAYMENT_CARD_NUMBER:
        await callback.answer("To'lov rekvizitlari hali sozlanmagan.", show_alert=True)
        return
    plan = get_plan(code)
    order = await create_payment_order(tenant_id, plan.price, plan_code=code)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Boshqa tarif", callback_data="menu:billing")
    builder.button(text="🏠 Bosh menyu", callback_data="menu:main")
    builder.adjust(1)
    holder = f"\nKarta egasi: <b>{PAYMENT_CARD_HOLDER}</b>" if PAYMENT_CARD_HOLDER else ""
    await callback.message.edit_text(
        f"✅ <b>{plan.name} tarifi</b>\n\n"
        f"Karta: <code>{PAYMENT_CARD_NUMBER}</code>{holder}\n"
        f"Aniq summa: <code>{format_som(order['amount'])}</code>\n"
        f"Buyurtma: <code>{order['order_code']}</code>\n\n"
        "Muhim: aynan ko'rsatilgan summani yuboring. To'lov aniqlangach tarif avtomatik yoqiladi.",
        reply_markup=builder.as_markup(),
    )
    await callback.answer()
