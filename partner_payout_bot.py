"""Hamkor bot uchun pul yechish arizalari va founder eslatmalari."""

import asyncio
import json
import logging
import re
from html import escape

from aiogram import Bot, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS
from services import partner_database as pdb
from services import partner_payouts

logger = logging.getLogger("janob_hr_partner")
payout_router = Router(name="partner_payout")
founder_payout_router = Router(name="founder_payout")


class PartnerPayoutForm(StatesGroup):
    full_name = State()
    card_number = State()
    receipt_username = State()


async def _require_approved_partner(message: Message) -> dict | None:
    partner = await pdb.get_partner_by_user_id(message.from_user.id)
    if not partner or partner["status"] != "approved":
        await message.answer("Bu bo'lim faqat tasdiqlangan hamkorlar uchun. /start yuboring.")
        return None
    return partner


def _payout_action_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ To'landi", callback_data=f"payout_paid:{request_id}"),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"payout_reject:{request_id}"),
            ]
        ]
    )


def _sale_breakdown(item: dict) -> str:
    metadata: dict = {}
    try:
        parsed = json.loads(item.get("metadata") or "{}")
        if isinstance(parsed, dict):
            metadata = parsed
    except (TypeError, ValueError, json.JSONDecodeError):
        pass

    plan_code = (item.get("plan_code") or "start").lower()
    sale_amount = int(item.get("sale_amount") or 0)
    net_commission = int(item.get("commission_amount") or 0)
    discount_amount = int(metadata.get("discount_amount") or 0)
    discount_type = metadata.get("discount_type") or (
        "percent" if int(metadata.get("discount_percent") or 0) else "amount"
    )
    discount_value = int(
        metadata.get("discount_value")
        or metadata.get("discount_percent")
        or (discount_amount if discount_type == "amount" else 0)
    )
    try:
        calculation = pdb.calculate_partner_payout(
            plan_code,
            discount_value if discount_type == "percent" else 0,
            discount_type=discount_type,
            discount_value=discount_value,
        )
    except (KeyError, TypeError, ValueError):
        calculation = None

    original = int((calculation or {}).get("original_amount") or sale_amount + discount_amount)
    base_commission = int(
        (calculation or {}).get("base_commission") or net_commission + discount_amount
    )
    discount_amount = int((calculation or {}).get("discount_amount") or discount_amount)
    discount_label = pdb.format_uzs(discount_amount) if discount_amount else "0 UZS"
    promo_code = metadata.get("promo_code") or ""
    promo_suffix = f" · promo {escape(str(promo_code))}" if promo_code else ""
    company = escape(item.get("company_name") or "Mijoz")
    plan = escape(plan_code.upper())
    return (
        f"• {company} — {plan}{promo_suffix}\n"
        f"  Tarif: {pdb.format_uzs(original)} → mijoz to'ladi: {pdb.format_uzs(sale_amount)}\n"
        f"  Komissiya: {pdb.format_uzs(base_commission)} − chegirma {discount_label} "
        f"= {pdb.format_uzs(net_commission)}"
    )


def _format_sales(items: list[dict], max_items: int = 12) -> str:
    if not items:
        return "—"
    lines: list[str] = []
    for item in items[:max_items]:
        tenant_id = item.get("tenant_id") or "—"
        lines.append(f"Tenant #{tenant_id}\n{_sale_breakdown(item)}")
    extra = len(items) - max_items
    if extra > 0:
        lines.append(f"... yana {extra} ta sotuv bor")
    return "\n".join(lines)


def _founder_payout_message(request: dict, *, title: str = "💸 Hamkor pul yechish arizasi") -> str:
    items = request.get("items") or []
    requested = int(request.get("requested_amount") or 0)
    bonus = int(request.get("bonus_amount") or 0)
    total = int(request.get("total_amount") or requested + bonus)
    delay_days = int(request.get("delay_days") or 0)
    payment_details = escape(request.get("payment_details") or "—")
    partner_name = escape(request.get("partner_name") or "Hamkor")
    payout_name = escape(request.get("payout_full_name") or request.get("partner_name") or "—")
    card_number = escape(request.get("payout_card_number") or "")
    receipt_username = request.get("receipt_telegram_username") or request.get("partner_username") or ""
    receipt_username = escape(str(receipt_username))
    if receipt_username and not receipt_username.startswith("@"):
        receipt_username = "@" + receipt_username
    username = escape(request.get("partner_username") or "")
    phone = escape(request.get("partner_phone") or "")

    return (
        f"{title} <b>#{request['id']}</b>\n\n"
        f"Hamkor: <b>{partner_name}</b> @{username or '—'}\n"
        f"Partner ID: <code>{request['partner_id']}</code>\n"
        f"Telefon: <code>{phone or '—'}</code>\n\n"
        f"<b>To'lov rekvizitlari:</b>\n"
        f"👤 Ism-familiya: <b>{payout_name}</b>\n"
        f"💳 Karta raqami: <code>{card_number or payment_details}</code>\n"
        f"🧾 Chek yuborish: <b>{receipt_username or '—'}</b>\n\n"
        f"<b>Real-time hisob-kitob:</b>\n"
        f"Asosiy komissiya: <b>{pdb.format_uzs(requested)}</b>\n"
        f"Kechikish bonusi: <b>{pdb.format_uzs(bonus)}</b> ({delay_days} kun × 3 000 UZS)\n"
        f"<b>Aniq o'tkazma: {pdb.format_uzs(total)}</b>\n"
        f"To'lov muddati: <b>{request.get('payout_due_date')}</b>\n"
        f"Ariza vaqti: <code>{request.get('requested_at')}</code>\n\n"
        f"Sana o'tgan bo'lsa, bonus keyingi har bir ish kuni uchun qayta hisoblanadi; "
        f"yakshanba va rasmiy bayramlar hisoblanmaydi.\n\n"
        f"<b>Qaysi mijozlardan komissiya:</b>\n{_format_sales(items)}\n\n"
        "🛡 Scam himoya: summa faqat real tasdiqlangan to'lovlardan yig'ildi; "
        "bu sotuvlar shu arizaga qulflandi, qayta yechishga tushmaydi."
    )


async def _notify_founders_about_payout(_source_bot: Bot | None, request: dict, *, title: str) -> None:
    """Send payout notifications from Founder Bot, never Partner Bot."""
    if not FOUNDER_BOT_TOKEN:
        logger.error("Payout notification yuborilmadi: FOUNDER_BOT_TOKEN sozlanmagan.")
        return
    founder_bot = Bot(
        token=FOUNDER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    text = _founder_payout_message(request, title=title)
    try:
        for founder_id in FOUNDER_USER_IDS:
            try:
                await founder_bot.send_message(
                    founder_id,
                    text,
                    reply_markup=_payout_action_keyboard(int(request["id"])),
                )
            except Exception:
                logger.exception("Founder Botga payout xabari yuborilmadi: %s", founder_id)
    finally:
        await founder_bot.session.close()


@payout_router.message(F.text == "💸 Pul yechish")
async def payout_start(message: Message, state: FSMContext) -> None:
    partner = await _require_approved_partner(message)
    if not partner:
        return

    balance = await partner_payouts.get_partner_balance(int(partner["id"]))
    active = balance.get("active_request")
    if active:
        await message.answer(
            f"⏳ Sizda #{active['id']} raqamli pul yechish arizasi hali yopilmagan.\n\n"
            f"Asosiy summa: <b>{pdb.format_uzs(active['requested_amount'])}</b>\n"
            f"Kechikish bonusi: <b>{pdb.format_uzs(active['bonus_amount'])}</b> ({active['delay_days']} kun)\n"
            f"Jami: <b>{pdb.format_uzs(active['total_amount'])}</b>\n"
            f"To'lov kuni: <b>{active['payout_due_date']}</b>"
        )
        return

    available = int(balance.get("available") or 0)
    if available <= 0:
        await message.answer(
            "Hozir yechish mumkin bo'lgan komissiya yo'q.\n\n"
            "Komissiya faqat mijoz tarif sotib olib, to'lovi tasdiqlangandan keyin balansga yoziladi."
        )
        return

    due = partner_payouts.next_payout_date()
    await state.set_state(PartnerPayoutForm.full_name)
    await message.answer(
        f"💸 <b>Pul yechish</b>\n\n"
        f"Yechish mumkin bo'lgan summa: <b>{pdb.format_uzs(available)}</b>\n"
        f"Keyingi to'lov muddati: <b>{due.isoformat()}</b>\n"
        "To'lov 1-, 11- yoki 21-sanada amalga oshiriladi. Yakshanba yoki rasmiy bayramga to'g'ri kelsa, keyingi ish kuniga suriladi.\n\n"
        "1/3. Pul oluvchining <b>ism-familiyasini</b> yozing:\n"
        "Masalan: <code>Jasur Karimov</code>"
    )


@payout_router.message(PartnerPayoutForm.full_name)
async def payout_full_name(message: Message, state: FSMContext) -> None:
    full_name = partner_payouts.normalize_payout_full_name(message.text or "")
    if len(full_name) < 5 or len(full_name.split()) < 2:
        await message.answer("Iltimos, ism va familiyangizni to'liq yozing. Masalan: <code>Jasur Karimov</code>")
        return
    await state.update_data(payout_full_name=full_name)
    await state.set_state(PartnerPayoutForm.card_number)
    await message.answer(
        "2/3. Pul tushadigan <b>karta raqamini</b> yuboring.\n"
        "Faqat 16–19 ta raqam bo'lsin; bo'sh joy bilan yuborsangiz ham bo'ladi.\n"
        "Masalan: <code>8600 1234 5678 9012</code>"
    )


@payout_router.message(PartnerPayoutForm.card_number)
async def payout_card_number(message: Message, state: FSMContext) -> None:
    card_number = partner_payouts.normalize_card_number(message.text or "")
    if len(card_number) not in {16, 17, 18, 19}:
        await message.answer("Karta raqami 16–19 ta raqamdan iborat bo'lishi kerak. Qayta yuboring.")
        return
    await state.update_data(payout_card_number=card_number)
    await state.set_state(PartnerPayoutForm.receipt_username)
    await message.answer(
        "3/3. Chek yuborish uchun <b>Telegram username</b>ingizni yuboring.\n"
        "Masalan: <code>@janobhr</code>"
    )


@payout_router.message(PartnerPayoutForm.receipt_username)
async def payout_receipt_username(message: Message, state: FSMContext) -> None:
    partner = await _require_approved_partner(message)
    if not partner:
        await state.clear()
        return

    receipt_username = partner_payouts.normalize_receipt_username(message.text or "")
    if not receipt_username or not re.fullmatch(r"@[A-Za-z0-9_]{5,32}", receipt_username):
        await message.answer("Telegram username @ bilan, masalan <code>@janobhr</code> bo'lishi kerak. Qayta yuboring.")
        return
    form_data = await state.get_data()
    result = await partner_payouts.create_payout_request(
        int(partner["id"]),
        form_data.get("payout_full_name") or "",
        form_data.get("payout_card_number") or "",
        receipt_username,
    )
    await state.clear()

    if not result.get("ok"):
        await message.answer(f"⚠️ {result.get('error') or 'Pul yechish arizasi yaratilmadi.'}")
        return

    logger.warning(
        "PARTNER_PAYOUT_REQUEST_CREATED id=%s partner_id=%s requested=%s total=%s due=%s items=%s",
        result["id"],
        result["partner_id"],
        result["requested_amount"],
        result["total_amount"],
        result["payout_due_date"],
        len(result.get("items") or []),
    )

    await message.answer(
        f"✅ Pul yechish arizangiz yuborildi.\n\n"
        f"Ariza: <b>#{result['id']}</b>\n"
        f"Asosiy summa: <b>{pdb.format_uzs(result['requested_amount'])}</b>\n"
        f"Kechikish bonusi hozircha: <b>{pdb.format_uzs(result['bonus_amount'])}</b>\n"
        f"Aniq o'tkazma: <b>{pdb.format_uzs(result['total_amount'])}</b>\n"
        f"To'lov kuni: <b>{result['payout_due_date']}</b>\n\n"
        "Founder Botga tafsilotlar bilan yuborildi. Sana o'tsa, kechikish bonusi real vaqtda qayta hisoblanadi."
    )
    await _notify_founders_about_payout(message.bot, result, title="💸 Hamkor pul yechish arizasi")
    await partner_payouts.mark_payout_notified(int(result["id"]), first=True)


@payout_router.callback_query(F.data.startswith("payout_paid:"))
@founder_payout_router.callback_query(F.data.startswith("payout_paid:"))
async def payout_paid(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    request_id = int(callback.data.split(":", 1)[1])
    request = await partner_payouts.set_payout_request_status(
        request_id, "paid", decided_by=callback.from_user.id
    )
    if not request or request.get("status") != "paid":
        await callback.answer("Ariza topilmadi yoki allaqachon yopilgan", show_alert=True)
        return

    logger.warning(
        "PARTNER_PAYOUT_PAID id=%s partner_id=%s paid_total=%s bonus=%s",
        request["id"],
        request["partner_id"],
        request["total_amount"],
        request["bonus_amount"],
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"✅ Payout #{request_id} to'landi deb belgilandi.\n"
        f"Jami: <b>{pdb.format_uzs(request['total_amount'])}</b>"
    )
    try:
        card = str(request.get("payout_card_number") or "")
        masked_card = f"**** {card[-4:]}" if len(card) >= 4 else "—"
        await callback.bot.send_message(
            int(request["partner_telegram_user_id"]),
            f"✅ Pul yechish arizangiz muvaffaqiyatli o'tkazildi.\n\n"
            f"Ariza: <b>#{request_id}</b>\n"
            f"Qabul qiluvchi: <b>{escape(request.get('payout_full_name') or request.get('partner_name') or '—')}</b>\n"
            f"Karta: <code>{masked_card}</code>\n"
            f"O'tkazilgan summa: <b>{pdb.format_uzs(request['total_amount'])}</b>\n\n"
            "🧾 To'lov tasdig'i chek sifatida yuborildi.\n"
            "Hamkorligingiz uchun rahmat! Shu tartibda ishlashda davom eting.",
        )
    except Exception:
        logger.exception("Partnerga payout paid xabari yuborilmadi: %s", request_id)
    await callback.answer("To'landi")


@payout_router.callback_query(F.data.startswith("payout_reject:"))
@founder_payout_router.callback_query(F.data.startswith("payout_reject:"))
async def payout_reject(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    request_id = int(callback.data.split(":", 1)[1])
    request = await partner_payouts.set_payout_request_status(
        request_id, "rejected", decided_by=callback.from_user.id
    )
    if not request or request.get("status") != "rejected":
        await callback.answer("Ariza topilmadi yoki allaqachon yopilgan", show_alert=True)
        return

    logger.warning(
        "PARTNER_PAYOUT_REJECTED id=%s partner_id=%s amount=%s",
        request["id"],
        request["partner_id"],
        request["requested_amount"],
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Payout #{request_id} rad etildi.")
    try:
        await callback.bot.send_message(
            int(request["partner_telegram_user_id"]),
            f"❌ Pul yechish arizangiz rad etildi.\n\nAriza: <b>#{request_id}</b>\nSavol bo'lsa shu chatga yozing.",
        )
    except Exception:
        logger.exception("Partnerga payout reject xabari yuborilmadi: %s", request_id)
    await callback.answer("Rad etildi")


async def run_payout_reminders(bot: Bot, interval_seconds: int = 3600) -> None:
    await asyncio.sleep(20)
    while True:
        try:
            requests = await partner_payouts.list_payout_requests_needing_reminder()
            for request in requests:
                logger.warning(
                    "PARTNER_PAYOUT_REMINDER id=%s partner_id=%s total=%s delay_days=%s due=%s",
                    request["id"],
                    request["partner_id"],
                    request["total_amount"],
                    request["delay_days"],
                    request["payout_due_date"],
                )
                await _notify_founders_about_payout(bot, request, title="⏰ Hamkor payout eslatmasi")
                await partner_payouts.mark_payout_notified(int(request["id"]))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Partner payout eslatmalarini yuborishda xato")
        await asyncio.sleep(interval_seconds)
