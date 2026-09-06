"""Hamkor bot uchun pul yechish arizalari va founder eslatmalari."""

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import FOUNDER_USER_IDS
from services import partner_database as pdb
from services import partner_payouts

logger = logging.getLogger("janob_hr_partner")
payout_router = Router(name="partner_payout")


class PartnerPayoutForm(StatesGroup):
    payment_details = State()


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


def _format_sales(items: list[dict], max_items: int = 12) -> str:
    if not items:
        return "—"
    lines: list[str] = []
    for i, item in enumerate(items[:max_items], start=1):
        company = escape(item.get("company_name") or "Mijoz")
        tenant_id = item.get("tenant_id") or "—"
        plan = escape((item.get("plan_code") or "tarif").upper())
        commission = pdb.format_uzs(int(item.get("commission_amount") or 0))
        sale_amount = pdb.format_uzs(int(item.get("sale_amount") or 0))
        lines.append(
            f"{i}) tenant #{tenant_id} — {company} — {plan}\n"
            f"   Mijoz to'lovi: {sale_amount} | Komissiya: <b>{commission}</b>"
        )
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
    username = escape(request.get("partner_username") or "")
    phone = escape(request.get("partner_phone") or "")

    return (
        f"{title} <b>#{request['id']}</b>\n\n"
        f"Hamkor: <b>{partner_name}</b> @{username or '—'}\n"
        f"Partner ID: <code>{request['partner_id']}</code>\n"
        f"Telefon: <code>{phone or '—'}</code>\n\n"
        f"Asosiy komissiya: <b>{pdb.format_uzs(requested)}</b>\n"
        f"Kechikish bonusi: <b>{pdb.format_uzs(bonus)}</b> ({delay_days} kun)\n"
        f"Jami to'lash kerak: <b>{pdb.format_uzs(total)}</b>\n"
        f"To'lov kuni: <b>{request.get('payout_due_date')}</b>\n"
        f"Ariza vaqti: <code>{request.get('requested_at')}</code>\n\n"
        f"To'lov ma'lumoti:\n<code>{payment_details}</code>\n\n"
        f"<b>Qaysi mijozlardan komissiya:</b>\n{_format_sales(items)}\n\n"
        "🛡 Scam himoya: summa faqat real tasdiqlangan to'lovlardan yig'ildi; "
        "bu sotuvlar shu arizaga qulflandi, qayta yechishga tushmaydi."
    )


async def _notify_founders_about_payout(bot: Bot, request: dict, *, title: str) -> None:
    text = _founder_payout_message(request, title=title)
    for founder_id in FOUNDER_USER_IDS:
        try:
            await bot.send_message(
                founder_id,
                text,
                reply_markup=_payout_action_keyboard(int(request["id"])),
            )
        except Exception:
            logger.exception("Founderga payout xabari yuborilmadi: %s", founder_id)


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

    await state.set_state(PartnerPayoutForm.payment_details)
    await message.answer(
        f"💸 <b>Pul yechish</b>\n\n"
        f"Yechish mumkin bo'lgan summa: <b>{pdb.format_uzs(available)}</b>\n"
        f"To'lov sanalari: <b>1-sana, 11-sana, 21-sana</b>.\n\n"
        "Karta raqamingiz yoki to'lov ma'lumotingizni bitta xabar qilib yuboring.\n"
        "Masalan: <code>9860 **** **** 1234, Ism Familiya</code>"
    )


@payout_router.message(PartnerPayoutForm.payment_details)
async def payout_payment_details(message: Message, state: FSMContext) -> None:
    partner = await _require_approved_partner(message)
    if not partner:
        await state.clear()
        return

    details = (message.text or "").strip()
    result = await partner_payouts.create_payout_request(int(partner["id"]), details)
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
        f"To'lov kuni: <b>{result['payout_due_date']}</b>\n\n"
        "Founder jamoaga eslatma yuborildi. Ariza yopilmaguncha shu sotuvlar qayta yechishga tushmaydi."
    )
    await _notify_founders_about_payout(message.bot, result, title="💸 Hamkor pul yechish arizasi")
    await partner_payouts.mark_payout_notified(int(result["id"]), first=True)


@payout_router.callback_query(F.data.startswith("payout_paid:"))
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
        await callback.bot.send_message(
            int(request["partner_telegram_user_id"]),
            f"✅ Pul yechish arizangiz to'landi.\n\n"
            f"Ariza: <b>#{request_id}</b>\n"
            f"Jami: <b>{pdb.format_uzs(request['total_amount'])}</b>",
        )
    except Exception:
        logger.exception("Partnerga payout paid xabari yuborilmadi: %s", request_id)
    await callback.answer("To'landi")


@payout_router.callback_query(F.data.startswith("payout_reject:"))
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
