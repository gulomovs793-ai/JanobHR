"""Admin bot ichidagi tarif, limit va to'lov oynasi."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import PAYMENT_CARD_HOLDER, PAYMENT_CARD_NUMBER
from services import database
from services import partner_database as pdb
from services.payment_automation import create_payment_order
from services.plans import PUBLIC_PLAN_CODES, format_som, get_plan, get_plan_transition

router = Router(name="admin_billing")


class BillingForm(StatesGroup):
    waiting_promo_code = State()


def _usage(value: int, limit: int | None) -> str:
    return f"{value} / {limit}" if limit is not None else f"{value} / ∞"


def _checkout_keyboard(plan_code: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎟 Promo kod kiritish", callback_data=f"billing:promo:{plan_code}")
    builder.button(text="✅ Promosiz davom etish", callback_data=f"billing:pay:{plan_code}")
    builder.button(text="⬅️ Boshqa tarif", callback_data="menu:billing")
    builder.adjust(1)
    return builder.as_markup()


def _order_keyboard(order_code: str):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Boshqa tarif", callback_data="menu:billing")
    builder.button(
        text="🔎 To'lovni tekshirish",
        callback_data=f"billing:check:{order_code}",
    )
    builder.button(text="🏠 Bosh menyu", callback_data="menu:main")
    builder.adjust(1)
    return builder.as_markup()


async def show_billing_message(message: Message, tenant_id: int) -> None:
    usage = await database.get_subscription_usage(tenant_id)
    plan = usage["plan"]
    expiry = (usage["expires_at"] or "—")[:10]
    builder = InlineKeyboardBuilder()
    for code in PUBLIC_PLAN_CODES:
        item = get_plan(code)
        builder.button(
            text=f"{item.name} — {format_som(item.price)}",
            callback_data=f"billing:buy:{code}",
        )
    builder.adjust(1)
    await message.answer(
        "💳 <b>Tarif va to'lov</b>\n\n"
        f"Joriy tarif: <b>{plan.name}</b>\n"
        f"Arizalar: <b>{_usage(usage['applications_used'], plan.application_limit)}</b>\n"
        f"Faol vakansiyalar: <b>{_usage(usage['vacancies_used'], plan.vacancy_limit)}</b>\n"
        f"Amal qilish sanasi: <b>{expiry}</b>\n\nTarifni tanlang:",
        reply_markup=builder.as_markup(),
    )


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


async def _validate_plan_or_alert(callback: CallbackQuery, tenant_id: int, code: str) -> bool:
    if code not in PUBLIC_PLAN_CODES:
        await callback.answer("Tarif topilmadi.", show_alert=True)
        return False
    if not PAYMENT_CARD_NUMBER:
        await callback.answer("To'lov rekvizitlari hali sozlanmagan.", show_alert=True)
        return False
    usage = await database.get_subscription_usage(tenant_id)
    transition = get_plan_transition(
        usage["plan"].code, code, current_expired=usage["expired"]
    )
    if transition == "blocked":
        expiry = (usage.get("expires_at") or "")[:10]
        suffix = f" ({expiry} gacha)" if expiry else ""
        await callback.answer(
            f"{usage['plan'].name} tarifi{suffix} faol. Past tarifni muddat tugagach tanlang.",
            show_alert=True,
        )
        return False
    return True


async def _create_order_payload(tenant_id: int, code: str, promo_code: str | None = None) -> tuple[bool, str, object | None]:
    plan = get_plan(code)
    attribution = await pdb.prepare_payment_attribution(
        tenant_id, code, promo_code=promo_code
    )
    if not attribution.get("ok"):
        return False, attribution.get("error") or "Promo kod ishlamadi.", None

    order_kwargs = {}
    if attribution.get("has_partner"):
        order_kwargs["attribution"] = attribution
    order = await create_payment_order(
        tenant_id,
        attribution["discounted_base_amount"],
        plan_code=code,
        **order_kwargs,
    )

    holder = (
        f"\nKarta egasi: <b>{PAYMENT_CARD_HOLDER}</b>" if PAYMENT_CARD_HOLDER else ""
    )
    lines = [f"✅ <b>{plan.name} tarifi</b>", ""]
    if attribution.get("has_partner"):
        lines.extend([
            f"Hamkor: <b>{attribution.get('partner_name') or 'Hamkor'}</b>",
        ])
        if attribution.get("promo_code"):
            discount_label = (
                f"{format_som(attribution['discount_value'])}"
                if attribution.get("discount_type") == "amount"
                else f"{attribution['discount_percent']}%"
            )
            lines.extend(
                [
                    f"Promo kod: <code>{attribution['promo_code']}</code>",
                    f"Chegirma: <b>{discount_label}</b> — {format_som(attribution['discount_amount'])}",
                    f"Narx: <s>{format_som(attribution['original_amount'])}</s> → <b>{format_som(attribution['discounted_base_amount'])}</b>",
                    "Chegirma hamkor komissiyasidan ayriladi.",
                    f"Hamkor komissiyasi: {format_som(attribution['base_commission'])} → {format_som(attribution['commission_amount'])}",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "Referral orqali kelgan mijoz sifatida qayd qilindi.",
                    f"Hamkor komissiyasi: {format_som(attribution['commission_amount'])}",
                    "",
                ]
            )

    lines.extend(
        [
            f"Karta: <code>{PAYMENT_CARD_NUMBER}</code>{holder}",
            f"Aniq summa: <code>{format_som(order['amount'])}</code>",
            f"Buyurtma: <code>{order['order_code']}</code>",
            "",
            "Muhim: aynan ko'rsatilgan summani yuboring. To'lov aniqlangach tarif avtomatik yoqiladi.",
            "",
            (
                "To'lovdan keyin tarif yoqilmasa yoki tushunarsiz holat bo'lsa, "
                f"<b>@F45746</b> ga buyurtma raqamini yuboring: <code>{order['order_code']}</code>"
            ),
        ]
    )
    return True, "\n".join(lines), _order_keyboard(order["order_code"])


@router.callback_query(F.data == "menu:billing")
async def billing_home(callback: CallbackQuery, tenant_id: int, state: FSMContext):
    await state.clear()
    await _show(callback, tenant_id)
    await callback.answer()


@router.callback_query(F.data.startswith("billing:buy:"))
async def billing_buy(callback: CallbackQuery, tenant_id: int):
    code = callback.data.rsplit(":", 1)[1]
    if not await _validate_plan_or_alert(callback, tenant_id, code):
        return
    plan = get_plan(code)
    await callback.message.edit_text(
        f"💳 <b>{plan.name} tarifi</b>\n\n"
        f"Narx: <b>{format_som(plan.price)}</b>\n\n"
        "Promo kodingiz bo'lsa kiriting. Promo kod chegirma beradi, lekin chegirma Janob HR hisobidan emas — hamkorning komissiyasidan ayriladi.\n\n"
        "Misol: START 299 000 so'm, 10% promo = 29 900 so'm chegirma. Hamkor komissiyasi 99 000 - 29 900 = 69 100 so'm.\n\n"
        "Qanday davom etamiz?",
        reply_markup=_checkout_keyboard(code),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("billing:pay:"))
async def billing_pay(callback: CallbackQuery, tenant_id: int):
    code = callback.data.rsplit(":", 1)[1]
    if not await _validate_plan_or_alert(callback, tenant_id, code):
        return
    ok, text, markup = await _create_order_payload(tenant_id, code)
    if not ok:
        await callback.answer(text, show_alert=True)
        return
    await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("billing:promo:"))
async def billing_promo(callback: CallbackQuery, tenant_id: int, state: FSMContext):
    code = callback.data.rsplit(":", 1)[1]
    if not await _validate_plan_or_alert(callback, tenant_id, code):
        return
    await state.update_data(billing_plan_code=code)
    await state.set_state(BillingForm.waiting_promo_code)
    await callback.message.edit_text(
        "🎟 Promo kodni yuboring.\n\n"
        "Masalan: <code>ABCD12310</code>\n\n"
        "Kod to'g'ri bo'lsa, chegirma avtomatik hisoblanadi."
    )
    await callback.answer()


@router.message(BillingForm.waiting_promo_code, F.text)
async def receive_promo_code(message: Message, tenant_id: int, state: FSMContext):
    data = await state.get_data()
    code = data.get("billing_plan_code")
    if code not in PUBLIC_PLAN_CODES:
        await state.clear()
        await message.answer("Tarif topilmadi. Tarif bo'limidan qayta boshlang.")
        return
    ok, text, markup = await _create_order_payload(tenant_id, code, promo_code=message.text.strip())
    if not ok:
        await message.answer(
            f"❌ {text}\n\nPromo kodni qayta yuboring yoki tarifni promosiz tanlang."
        )
        return
    await state.clear()
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("billing:check:"))
async def billing_check(callback: CallbackQuery, tenant_id: int):
    code = callback.data.rsplit(":", 1)[1]
    order = await database.get_payment_order_for_tenant(tenant_id, code)
    if not order:
        await callback.answer("Buyurtma topilmadi.", show_alert=True)
        return
    labels = {
        "awaiting_payment": "⏳ To'lov hali aniqlanmadi",
        "approved": "✅ To'lov qabul qilindi, tarif yoqilgan",
        "needs_review": "⚠️ To'lov qo'lda tekshirilmoqda",
        "cancelled": "❌ Buyurtma bekor qilingan",
        "expired": "⌛ Buyurtma muddati tugagan — yangi buyurtma oching",
    }
    await callback.answer(labels.get(order["status"], order["status"]), show_alert=True)
