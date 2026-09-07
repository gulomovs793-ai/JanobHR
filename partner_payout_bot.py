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
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import FOUNDER_BOT_TOKEN, FOUNDER_USER_IDS, PARTNER_BOT_TOKEN
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
    username = escape(str(request.get("partner_username") or "").lstrip("@"))
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


async def _notify_founders_about_payout(
    _source_bot: Bot | None, request: dict, *, title: str
) -> bool:
    """Send payout notifications from Founder Bot, never Partner Bot."""
    if not FOUNDER_BOT_TOKEN or not FOUNDER_USER_IDS:
        logger.error("Payout notification yuborilmadi: FOUNDER_BOT_TOKEN sozlanmagan.")
        return False
    founder_bot = Bot(
        token=FOUNDER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    text = _founder_payout_message(request, title=title)
    sent_any = False
    try:
        for founder_id in FOUNDER_USER_IDS:
            try:
                await founder_bot.send_message(
                    founder_id,
                    text,
                    reply_markup=_payout_action_keyboard(int(request["id"])),
                )
                sent_any = True
            except Exception:
                logger.exception("Founder Botga payout xabari yuborilmadi: %s", founder_id)
    finally:
        await founder_bot.session.close()
    return sent_any


async def notify_founders_about_payout(
    request: dict, *, title: str = "💸 Hamkor pul yechish arizasi"
) -> bool:
    """Expose the Founder Bot notification for the Mini App API as well."""
    return await _notify_founders_about_payout(None, request, title=title)


def _partner_paid_message(request: dict) -> str:
    card = str(request.get("payout_card_number") or "")
    masked_card = f"**** {card[-4:]}" if len(card) >= 4 else "—"
    return (
        "✅ Pul yechish arizangiz muvaffaqiyatli o'tkazildi.\n\n"
        f"Ariza: <b>#{request['id']}</b>\n"
        f"Qabul qiluvchi: <b>{escape(request.get('payout_full_name') or request.get('partner_name') or '—')}</b>\n"
        f"Karta: <code>{masked_card}</code>\n"
        f"O'tkazilgan summa: <b>{pdb.format_uzs(request['total_amount'])}</b>\n\n"
        "🧾 To'lov tasdig'i chek sifatida yuborildi.\n"
        "Hamkorligingiz uchun rahmat! Shu tartibda ishlashda davom eting."
    )


async def _notify_partner_about_payout(request: dict, text: str) -> bool:
    """Notify the partner through Partner Bot, even when Founder Bot handled the click."""
    if not PARTNER_BOT_TOKEN or not request.get("partner_telegram_user_id"):
        logger.error("Partner payout xabari yuborilmadi: Partner Bot sozlanmagan.")
        return False
    partner_bot = Bot(
        token=PARTNER_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    try:
        await partner_bot.send_message(int(request["partner_telegram_user_id"]), text)
        return True
    except Exception:
        logger.exception("Partnerga payout xabari yuborilmadi: %s", request.get("id"))
        return False
    finally:
        await partner_bot.session.close()


def _callback_request_id(data: str | None, prefix: str) -> int | None:
    if not isinstance(data, str) or not data.startswith(prefix):
        return None
    raw_id = data[len(prefix) :]
    if not raw_id.isdecimal():
        return None
    try:
        request_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    return request_id if request_id > 0 else None


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

    founder_notified = await _notify_founders_about_payout(
        message.bot, result, title="💸 Hamkor pul yechish arizasi"
    )
    if founder_notified:
        await partner_payouts.mark_payout_notified(int(result["id"]), first=True)
    notification_text = (
        "Founder Botga tafsilotlar bilan yuborildi."
        if founder_notified
        else "⚠️ Founder Botga avtomatik notification yuborilmadi; admin sozlamani tekshiradi."
    )
    await message.answer(
        f"✅ Pul yechish arizangiz yuborildi.\n\n"
        f"Ariza: <b>#{result['id']}</b>\n"
        f"Asosiy summa: <b>{pdb.format_uzs(result['requested_amount'])}</b>\n"
        f"Kechikish bonusi hozircha: <b>{pdb.format_uzs(result['bonus_amount'])}</b>\n"
        f"Aniq o'tkazma: <b>{pdb.format_uzs(result['total_amount'])}</b>\n"
        f"To'lov kuni: <b>{result['payout_due_date']}</b>\n\n"
        f"{notification_text} Sana o'tsa, kechikish bonusi real vaqtda qayta hisoblanadi."
    )


@payout_router.callback_query(F.data.startswith("payout_paid:"))
@founder_payout_router.callback_query(F.data.startswith("payout_paid:"))
async def payout_paid(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    request_id = _callback_request_id(callback.data, "payout_paid:")
    if request_id is None:
        await callback.answer("Ariza identifikatori noto'g'ri.", show_alert=True)
        return
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
    claimed = await partner_payouts.claim_paid_payout_notification(
        request_id, retry_after_seconds=0
    )
    partner_notified = False
    if claimed:
        partner_notified = await _notify_partner_about_payout(
            claimed, _partner_paid_message(claimed)
        )
        await partner_payouts.mark_partner_payout_notified(
            request_id,
            error=None if partner_notified else "Partner Bot orqali xabar yuborilmadi",
        )
    await callback.answer(
        "To'landi va partnerga xabar yuborildi."
        if partner_notified
        else "To'landi. Partner xabari recovery orqali qayta yuboriladi.",
        show_alert=not partner_notified,
    )


@payout_router.callback_query(F.data.startswith("payout_reject:"))
@founder_payout_router.callback_query(F.data.startswith("payout_reject:"))
async def payout_reject(callback: CallbackQuery) -> None:
    if callback.from_user.id not in FOUNDER_USER_IDS:
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
    request_id = _callback_request_id(callback.data, "payout_reject:")
    if request_id is None:
        await callback.answer("Ariza identifikatori noto'g'ri.", show_alert=True)
        return
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
    partner_notified = await _notify_partner_about_payout(
        request,
        f"❌ Pul yechish arizangiz rad etildi.\n\nAriza: <b>#{request_id}</b>\nSavol bo'lsa shu chatga yozing.",
    )
    await callback.answer(
        "Rad etildi" if partner_notified else "Rad etildi, partnerga xabar yuborilmadi.",
        show_alert=not partner_notified,
    )


async def run_payout_reminders(
    _source_bot: Bot | None = None, interval_seconds: int = 3600
) -> None:
    """Remind founders from the shared webhook service.

    ``_source_bot`` remains an optional compatibility argument for the old
    polling entry point; notifications are always sent through Founder Bot.
    """
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
                notified = await _notify_founders_about_payout(
                    _source_bot, request, title="⏰ Hamkor payout eslatmasi"
                )
                if notified:
                    await partner_payouts.mark_payout_notified(int(request["id"]))
            for request in await partner_payouts.list_paid_payouts_needing_partner_notification():
                claimed = await partner_payouts.claim_paid_payout_notification(
                    int(request["id"])
                )
                if not claimed:
                    continue
                notified = await _notify_partner_about_payout(
                    claimed, _partner_paid_message(claimed)
                )
                await partner_payouts.mark_partner_payout_notified(
                    int(claimed["id"]),
                    error=None if notified else "Partner Bot orqali xabar yuborilmadi",
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Partner payout eslatmalarini yuborishda xato")
        await asyncio.sleep(interval_seconds)
