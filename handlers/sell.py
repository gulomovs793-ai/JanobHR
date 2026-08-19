"""
Janob HR Bot — "Sell" bosqichi va suhbat vaqtini tanlash.

Ikki holatda ishlatiladi:
1. Nomzod yuqori AI ball olsa (SELL_SCORE_THRESHOLD dan yuqori) — arizadan
   so'ng darhol avtomatik taklif yuboriladi (maybe_send_sell_pitch).
2. Admin "✅ Suhbatga chaqirish" tugmasini bossa — admin_bot/handlers_decisions.py
   shu yerdagi send_slot_offer() funksiyasini chaqirib, nomzodga vaqt tanlashni
   taklif qiladi.

Vaqtlar endi Admin bot orqali (📅 Suhbat vaqtlari) dinamik boshqariladi —
sana+soat va sig'imi bilan. Har biri cheklangan sig'imga ega — band bo'lgan
vaqtlar keyingi nomzodlarga umuman ko'rsatilmaydi.

MUHIM (til haqida): tugma bosilgan payt (handle_slot_choice) nomzodning FSM
suhbat holati allaqachon tozalangan bo'lishi mumkin (ariza tugagan, yoki admin
uni ancha keyinroq qabul qilgan bo'lishi mumkin) — shuning uchun til FSM'dan
emas, ARIZANING O'ZIDA (bazada) saqlangan `lang` maydonidan olinadi.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import COMPANY_PITCH_IMAGE_URL, COMPANY_PITCH_TEXT, SELL_SCORE_THRESHOLD
from i18n import DEFAULT_LANG, t
from services import database
from services.ai_scoring import aggregate_scores

logger = logging.getLogger("janob_hr_bot")

router = Router(name="sell")


async def send_slot_offer(bot, chat_id: int, app_id: int, intro_text: str, lang: str = DEFAULT_LANG) -> bool:
    """Nomzodga bo'sh suhbat vaqtlarini tugmalar bilan taklif qiladi.

    Hech qanday vaqt qo'shilmagan yoki barchasi band bo'lsa, buning o'rniga
    "operator bog'lanadi" xabarini yuborib, False qaytaradi.
    """
    slots = await database.get_available_interview_slots()

    if not slots:
        await bot.send_message(chat_id=chat_id, text=f"{intro_text}\n\n{t('no_slots_left', lang)}")
        return False

    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot["label"], callback_data=f"slot:{app_id}:{slot['id']}")
    builder.adjust(1)

    await bot.send_message(
        chat_id=chat_id,
        text=t("slot_offer_pick", lang, intro_text=intro_text),
        reply_markup=builder.as_markup(),
    )
    return True


async def maybe_send_sell_pitch(message: Message, app_id: int, ai_scores: dict, lang: str = DEFAULT_LANG):
    """Shartlar bajarilsa (yuqori ball, qizil bayroq yo'q), nomzodga taklif yuboradi."""
    aggregate = aggregate_scores(ai_scores)
    if not aggregate:
        return  # AI baholash yoqilmagan yoki hech qanday ai_score savoli yo'q

    if aggregate["avg_score"] < SELL_SCORE_THRESHOLD or aggregate["verdict"] == "qizil":
        return

    slots = await database.get_available_interview_slots()
    if not slots:
        return  # Vaqt umuman qo'shilmagan bo'lsa, pitch yubormaymiz (operator qo'lda bog'lanadi)

    builder = InlineKeyboardBuilder()
    for slot in slots:
        builder.button(text=slot["label"], callback_data=f"slot:{app_id}:{slot['id']}")
    builder.adjust(1)

    caption = t("slot_offer_pick", lang, intro_text=COMPANY_PITCH_TEXT)

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


async def _send_interview_details(bot, chat_id: int, lang: str):
    """Vaqt band qilingandan keyin: manzil, intervyuchi kontakti va eslatma."""
    settings = await database.get_interview_settings()

    if settings.get("location_lat") is not None:
        try:
            await bot.send_location(
                chat_id=chat_id,
                latitude=settings["location_lat"],
                longitude=settings["location_lng"],
            )
        except Exception:
            logger.exception("Lokatsiyani yuborib bo'lmadi (chat_id=%s).", chat_id)
    elif settings.get("location_text"):
        await bot.send_message(
            chat_id=chat_id, text=t("interview_location_prefix", lang, location=settings["location_text"])
        )

    contact_lines = []
    if settings.get("interviewer_name") or settings.get("interviewer_phone"):
        contact_lines.append(t("interview_contact_header", lang))
        if settings.get("interviewer_name"):
            contact_lines.append(f"   {settings['interviewer_name']}")
        if settings.get("interviewer_phone"):
            contact_lines.append(f"   {t('interview_phone_prefix', lang, phone=settings['interviewer_phone'])}")
    if settings.get("notes"):
        contact_lines.append("")
        contact_lines.append(settings["notes"])

    if contact_lines:
        await bot.send_message(chat_id=chat_id, text="\n".join(contact_lines))


@router.callback_query(F.data.startswith("slot:"))
async def handle_slot_choice(callback: CallbackQuery, state: FSMContext):
    from handlers.admin import notify_admin_slot_selected

    _, app_id_str, slot_id_str = callback.data.split(":")
    app_id = int(app_id_str)
    slot_id = int(slot_id_str)

    # Til FSM'dan emas, arizaning o'zidan olinadi — chunki bu tugma ancha
    # keyinroq (masalan admin qabul qilgandan keyin) bosilishi mumkin, o'sha
    # payt FSM holati allaqachon boshqa narsa yoki bo'sh bo'lishi mumkin.
    app = await database.get_application(app_id)
    lang = (app or {}).get("lang", DEFAULT_LANG)

    all_slots = await database.list_interview_slots(active_only=True)
    slot = next((s for s in all_slots if s["id"] == slot_id), None)
    if not slot:
        await callback.answer(t("no_slots_left", lang), show_alert=True)
        return

    # Atomik "band qilish" — boshqa nomzod bir zumda oldinroq ulgurgan bo'lishi mumkin.
    booked = await database.try_book_slot(app_id, slot["label"], slot["capacity"])

    if not booked:
        await callback.answer(t("slot_taken_retry", lang), show_alert=True)
        # Xabarni yangilab, faqat hali bo'sh qolgan vaqtlarni ko'rsatamiz.
        remaining = await database.get_available_interview_slots()
        try:
            if not remaining:
                base_text = callback.message.caption or callback.message.text or ""
                new_text = f"{base_text}\n\n{t('no_slots_left', lang)}"
                if callback.message.caption is not None:
                    await callback.message.edit_caption(caption=new_text, reply_markup=None)
                else:
                    await callback.message.edit_text(new_text, reply_markup=None)
            else:
                builder = InlineKeyboardBuilder()
                for r_slot in remaining:
                    builder.button(text=r_slot["label"], callback_data=f"slot:{app_id}:{r_slot['id']}")
                builder.adjust(1)
                if callback.message.caption is not None:
                    await callback.message.edit_caption(reply_markup=builder.as_markup())
                else:
                    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
        except Exception:
            logger.exception("Bo'sh vaqtlar ro'yxatini yangilab bo'lmadi (app_id=%s).", app_id)
        return

    await callback.answer(t("slot_choice_accepted", lang))

    try:
        base_text = callback.message.caption or callback.message.text or ""
        confirmation = f"{base_text}\n\n{t('slot_confirmed', lang, label=slot['label'])}"
        if callback.message.caption is not None:
            await callback.message.edit_caption(caption=confirmation, reply_markup=None)
        else:
            await callback.message.edit_text(confirmation, reply_markup=None)
    except Exception:
        logger.exception("Sell xabarini yangilab bo'lmadi (app_id=%s).", app_id)

    # Manzil, intervyuchi kontakti va eslatmani yuboramiz.
    try:
        await _send_interview_details(callback.bot, callback.from_user.id, lang)
    except Exception:
        logger.exception("Suhbat tafsilotlarini yuborib bo'lmadi (app_id=%s).", app_id)

    try:
        await notify_admin_slot_selected(app_id, slot["label"])
    except Exception:
        logger.exception("Adminlarga vaqt tanlovi haqida xabar berib bo'lmadi (app_id=%s).", app_id)
