"""
Janob HR Bot — "Sell" bosqichi.

Nomzod yuqori AI ball olsa (SELL_SCORE_THRESHOLD dan yuqori, jiddiy qizil
bayroqsiz), bot avtomatik unga kompaniya taqdimotini va suhbat vaqtini
tanlash tugmalarini yuboradi — A-Playerlarni kutish holatida qoldirmaslik
uchun.

Har bir vaqt oralig'i cheklangan sig'imga ega (SLOT_CAPACITY, standart 1) —
band bo'lgan vaqtlar keyingi nomzodlarga umuman ko'rsatilmaydi, shuning
uchun ikkita odam bir xil vaqtga "taqdim" bo'lib qolmaydi.
"""
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import (
    COMPANY_PITCH_IMAGE_URL,
    COMPANY_PITCH_TEXT,
    INTERVIEW_SLOTS,
    SELL_SCORE_THRESHOLD,
    SLOT_CAPACITY,
)
from services import database
from services.ai_scoring import aggregate_scores

logger = logging.getLogger("janob_hr_bot")

router = Router(name="sell")

_NO_SLOTS_LEFT_TEXT = (
    "Barcha suhbat vaqtlari hozircha band bo'lib qoldi 🙏 Tashvishlanmang — "
    "operatorimiz tez orada siz bilan bog'lanib, individual vaqt belgilaydi."
)


async def _available_slots() -> list[tuple[int, str]]:
    """(index, vaqt_matni) juftliklarini — faqat hali joyi bor bo'lganlarini — qaytaradi."""
    available = []
    for idx, slot in enumerate(INTERVIEW_SLOTS):
        booked = await database.count_slot_bookings(slot)
        if booked < SLOT_CAPACITY:
            available.append((idx, slot))
    return available


async def maybe_send_sell_pitch(message: Message, app_id: int, ai_scores: dict):
    """Shartlar bajarilsa (yuqori ball, qizil bayroq yo'q), nomzodga taklif yuboradi."""
    aggregate = aggregate_scores(ai_scores)
    if not aggregate:
        return  # AI baholash yoqilmagan yoki hech qanday ai_score savoli yo'q

    if aggregate["avg_score"] < SELL_SCORE_THRESHOLD or aggregate["verdict"] == "qizil":
        return

    if not INTERVIEW_SLOTS:
        return

    slots = await _available_slots()

    if not slots:
        # Barcha vaqtlar band — tugmasiz, operator orqali qo'lda rejalashtiriladi.
        await message.answer(f"{COMPANY_PITCH_TEXT}\n\n{_NO_SLOTS_LEFT_TEXT}")
        return

    builder = InlineKeyboardBuilder()
    for idx, slot in slots:
        builder.button(text=slot, callback_data=f"slot:{app_id}:{idx}")
    builder.adjust(1)

    caption = f"{COMPANY_PITCH_TEXT}\n\n📅 Qulay bo'lgan vaqtni tanlang:"

    if COMPANY_PITCH_IMAGE_URL:
        try:
            await message.answer_photo(
                photo=COMPANY_PITCH_IMAGE_URL,
                caption=caption,
                reply_markup=builder.as_markup(),
            )
            return
        except Exception:
            logger.exception("Pitch rasmini yuborib bo'lmadi, oddiy matn bilan davom etamiz.")

    await message.answer(caption, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("slot:"))
async def handle_slot_choice(callback: CallbackQuery):
    from handlers.admin import notify_admin_slot_selected

    _, app_id_str, idx_str = callback.data.split(":")
    app_id = int(app_id_str)
    idx = int(idx_str)

    if idx >= len(INTERVIEW_SLOTS):
        await callback.answer("Bu tanlov endi mavjud emas.", show_alert=True)
        return

    slot = INTERVIEW_SLOTS[idx]

    # Atomik "band qilish" — boshqa nomzod bir zumda oldinroq ulgurgan bo'lishi mumkin.
    booked = await database.try_book_slot(app_id, slot, SLOT_CAPACITY)

    if not booked:
        await callback.answer(
            "Afsuski, bu vaqtni sizdan oldin boshqa nomzod band qildi 🙏 "
            "Boshqa vaqtni tanlang.",
            show_alert=True,
        )
        # Xabarni yangilab, faqat hali bo'sh qolgan vaqtlarni ko'rsatamiz.
        remaining = await _available_slots()
        try:
            if not remaining:
                base_text = callback.message.caption or callback.message.text or ""
                new_text = f"{base_text}\n\n{_NO_SLOTS_LEFT_TEXT}"
                if callback.message.caption is not None:
                    await callback.message.edit_caption(caption=new_text, reply_markup=None)
                else:
                    await callback.message.edit_text(new_text, reply_markup=None)
            else:
                builder = InlineKeyboardBuilder()
                for r_idx, r_slot in remaining:
                    builder.button(text=r_slot, callback_data=f"slot:{app_id}:{r_idx}")
                builder.adjust(1)
                if callback.message.caption is not None:
                    await callback.message.edit_caption(reply_markup=builder.as_markup())
                else:
                    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
        except Exception:
            logger.exception("Bo'sh vaqtlar ro'yxatini yangilab bo'lmadi (app_id=%s).", app_id)
        return

    await callback.answer("Tanlovingiz qabul qilindi ✅")

    try:
        base_text = callback.message.caption or callback.message.text or ""
        confirmation = f"{base_text}\n\n✅ Siz tanladingiz: <b>{slot}</b>"
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=confirmation, reply_markup=None)
        else:
            await callback.message.edit_text(confirmation, reply_markup=None)
    except Exception:
        logger.exception("Sell xabarini yangilab bo'lmadi (app_id=%s).", app_id)

    try:
        await notify_admin_slot_selected(callback.bot, app_id, slot)
    except Exception:
        logger.exception("Admin guruhga vaqt tanlovi haqida xabar berib bo'lmadi (app_id=%s).", app_id)
