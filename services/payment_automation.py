"""
Janob HR — to'lovni avtomatlashtirish: noyob summa orqali moslashtirish.

O'zbek Ovoz AI loyihasidagi (haqiqiy, ishlab turgan) mexanizmning Python/
SQLite'ga moslashtirilgan versiyasi. Asosiy g'oya o'zgarmagan:

1. Mijoz to'lov qilmoqchi bo'lganda, unga BAZAVIY narxga kichik tasodifiy
   summa (1-200 so'm) qo'shilgan, hozircha ochiq boshqa buyurtmalar orasida
   NOYOB summa beriladi.
2. Kartaga pul tushganda, bank bildirishnomasi matni bu yerga keladi
   (userbot.py orqali).
3. Matndan summa ajratib olinadi, chiquvchi/xato tranzaksiyalar chetlab
   o'tiladi, karta raqami tekshiriladi, so'ng aynan shu summali ochiq
   buyurtma qidiriladi.
4. Mos kelsa — ADMIN ISHTIROKISIZ, avtomatik ravishda mijoz (tenant)
   faollashtiriladi.

Xavfsizlik: bu yerda xato — pulsiz faollashtirish yoki chalkash faollash-
tirish degani, shuning uchun har bir tekshiruv O'ZBEK OVOZ AI'dagi bilan
bir xil qat'iylikda saqlangan.
"""

import hashlib
import logging
import random
import re
from datetime import datetime, timedelta, timezone

from config import MONTHLY_PRICE_SOM, ORDER_TTL_MINUTES, PAYMENT_CARD_NUMBER
from services import database

logger = logging.getLogger("janob_hr_bot")

_NOTIFY_EXCLUDE_KEYWORDS = [
    "spisan",
    "spisano",
    "spisanie",  # yechib olindi — bu CHIQUVCHI tranzaksiya
    "otmen",
    "otkaz",
    "cancel",  # bekor qilindi
    "oshibk",
    "error",
    "fail",  # xatolik
    "nedostatoch",
    "insufficient",  # mablag' yetarli emas
    "vozvrat",
    "refund",  # qaytarish
    "zapros",
    "otklon",
    "declin",  # so'rov rad etildi
]


def looks_like_failed_or_outgoing(text: str) -> bool:
    """Bildirishnoma matni chiquvchi/muvaffaqiyatsiz tranzaksiyaga tegishli
    belgilarni o'z ichiga oladimi?"""
    t = text.lower()
    if any(k in t for k in _NOTIFY_EXCLUDE_KEYWORDS):
        return True

    lines = [line.strip() for line in (text or "").splitlines()]
    has_incoming = any(re.match(r"^(\+|➕)", line) for line in lines)
    has_outgoing = any(re.match(r"^(-|−|➖)", line) for line in lines)
    return bool(has_outgoing and not has_incoming)


def _extract_amount(text: str) -> int | None:
    """Bitta satrdan summani ajratib oladi."""
    m = re.search(
        r"(\d[\d\s.,']{1,15}\d|\d)\s*(?:so'?m|сўм|сум|sum|som|uzs)",
        text or "",
        re.IGNORECASE,
    )
    if not m:
        return None

    raw = re.sub(r"[\s']", "", m.group(1))
    decimal_tail = re.match(r"^([\d.,]*?)[.,](\d{2})$", raw)
    raw = (
        re.sub(r"[.,]", "", decimal_tail.group(1))
        if decimal_tail
        else re.sub(r"[.,]", "", raw)
    )

    try:
        n = int(raw)
        return n if n > 0 else None
    except ValueError:
        return None


def parse_notification_amount(text: str) -> int | None:
    """Bank/karta bildirishnomasi matnidan summani (butun so'mda) ajratib
    oladi. Kirim ("+") qatori BALANS qatoridan ustun qo'yiladi."""
    raw = text or ""

    for line in raw.splitlines():
        t = line.strip()
        if not re.match(r"^(\+|➕)", t):
            continue
        n = _extract_amount(t)
        if n is not None:
            return n

    for line in raw.splitlines():
        t = line.strip()
        if re.search(r"balans|balance|dostupno|ostatok|💵", t, re.IGNORECASE):
            continue
        n = _extract_amount(t)
        if n is not None:
            return n

    return _extract_amount(raw)


def card_matches_ours(text: str) -> bool:
    """Bildirishnomadagi karta raqami bizning to'lov kartamizga mos keladimi?"""
    our_digits = re.sub(r"\D", "", PAYMENT_CARD_NUMBER or "")
    if len(our_digits) < 4:
        return True  # Sozlanmagan — tekshirmaymiz.
    our_last4 = our_digits[-4:]

    found = re.findall(r"[*x•·]{2,}\s*(\d{4})", text or "", re.IGNORECASE)
    if not found:
        return True  # Karta ko'rsatilmagan.

    return our_last4 in found


def _new_order_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # O/0, I/1 chalkashmasin
    suffix = "".join(random.choice(alphabet) for _ in range(6))
    return f"JH-{suffix}"


async def _pick_unique_amount(base_price: int) -> int:
    """Bazaviy narxga kichik tasodifiy summa qo'shib, ochiq buyurtmalar
    orasida noyob ekanini tekshiradi."""
    for _ in range(25):
        offset = random.randint(1, 200)
        candidate = base_price + offset
        if not await database.get_open_payment_order_by_amount(candidate):
            return candidate
    return base_price + random.randint(1, 200)


async def create_payment_order(
    tenant_id: int,
    base_amount: int | None = None,
    *,
    plan_code: str = "start",
    billing_months: int = 1,
) -> dict:
    """Mijoz uchun yangi to'lov buyurtmasi yaratadi (avvalgi ochiq
    buyurtmalarini bekor qilib). Noyob summa va tugash muddati bilan."""
    base_amount = base_amount or MONTHLY_PRICE_SOM

    await database.cancel_open_payment_orders_for_tenant(tenant_id)

    amount = await _pick_unique_amount(base_amount)
    order_code = _new_order_code()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=ORDER_TTL_MINUTES)
    ).isoformat()

    order_id = await database.create_payment_order(
        tenant_id=tenant_id,
        order_code=order_code,
        base_amount=base_amount,
        amount=amount,
        expires_at=expires_at,
        plan_code=plan_code,
        billing_months=billing_months,
    )
    return {
        "id": order_id,
        "order_code": order_code,
        "amount": amount,
        "expires_at": expires_at,
        "plan_code": plan_code,
    }


async def handle_payment_notification(
    raw_text: str, notify_founders, activate_tenant
) -> dict:
    """Userbot orqali kelgan xom bildirishnoma matnini qayta ishlaydi.

    `notify_founders(text: str)` — asoschilarga xabar yuborish uchun async chaqiruv.
    `activate_tenant(tenant_id: int)` — mos buyurtma topilganda tenantni
    faollashtiruvchi async chaqiruv (webhooklarni o'rnatish va h.k.).
    """
    text = (raw_text or "").strip()
    if not text:
        return {"status": "no_amount"}

    if looks_like_failed_or_outgoing(text):
        logger.info(
            "[to'lov] chiquvchi/muvaffaqiyatsiz tranzaksiya, e'tiborsiz qoldirildi."
        )
        return {"status": "ignored_excluded"}

    if not card_matches_ours(text):
        found_cards = re.findall(r"[*x•·]{2,}\s*(\d{4})", text, re.IGNORECASE)
        our_digits = re.sub(r"\D", "", PAYMENT_CARD_NUMBER or "")
        logger.warning(
            "[to'lov] boshqa kartaga tegishli bildirishnoma, e'tiborsiz qoldirildi."
        )
        await notify_founders(
            f"⚠️ Bildirishnoma karta bo'yicha rad etildi.\n"
            f"Matnda topilgan karta: {', '.join(found_cards) or 'aniqlanmadi'}\n"
            f"Sozlangan kartaning oxiri: {our_digits[-4:] if our_digits else 'yoq'}\n\n"
            f"Agar bu SIZNING to'lovingiz bo'lsa, PAYMENT_CARD_NUMBER Render'da noto'g'ri sozlangan bo'lishi mumkin."
        )
        return {"status": "ignored_excluded"}

    amount = parse_notification_amount(text)
    if not amount:
        return {"status": "no_amount"}

    # --- Takrorlashdan himoya (30 daqiqa ichida bir xil matn) ---
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if await database.was_notification_seen_recently(text_hash, minutes=30):
        return {"status": "duplicate", "amount": amount}
    await database.record_seen_notification(text_hash, amount)

    candidates = await database.get_open_payment_orders_by_amount(amount)

    if not candidates:
        open_orders = await database.list_open_payment_orders()
        open_summary = (
            ", ".join(f"{o['order_code']}={o['amount']}" for o in open_orders) or "yo'q"
        )
        await notify_founders(
            f"⚠️ Noma'lum to'lov bildirishnomasi.\n\nAniqlangan summa: {amount:,} so'm\n"
            f"Matn: {text[:300]}\n\nJoriy ochiq buyurtmalar: {open_summary}\n\n"
            "Hech qanday ochiq buyurtmaga mos kelmadi."
        )
        logger.warning(
            "[to'lov] Mos kelmadi: amount=%s, ochiq buyurtmalar=%s",
            amount,
            open_summary,
        )
        await database.forget_payment_notification(text_hash)
        return {"status": "no_match", "amount": amount}

    if len(candidates) > 1:
        codes = ", ".join(o["order_code"] for o in candidates)
        await notify_founders(
            f"⚠️ Noaniq to'lov: {amount:,} so'm bir nechta buyurtmaga mos keldi: {codes}\n\nQo'lda tekshiring."
        )
        return {"status": "ambiguous", "amount": amount}

    order = candidates[0]

    # --- Atomik tasdiqlash (parallel bildirishnoma ikki marta faollashtirmasligi uchun) ---
    won = await database.try_approve_payment_order(order["id"])
    if not won:
        return {"status": "duplicate", "amount": amount}

    try:
        activation = await activate_tenant(order["tenant_id"])
        if not activation or not activation.get("ok"):
            error = (activation or {}).get("error", "Noma'lum faollashtirish xatosi")
            raise RuntimeError(error)
        await database.activate_subscription(
            order["tenant_id"],
            order.get("plan_code", "start"),
            order.get("billing_months", 1),
        )
    except Exception:
        logger.exception(
            "Tolov aniqlandi, lekin tenantni faollashtirishda xato (order=%s).",
            order["order_code"],
        )
        await database.mark_payment_order_needs_review(order["id"], str(text[:200]))
        await notify_founders(
            f"🚨 Avtomatik tasdiqlash xatosi: {order['order_code']} to'lovi aniqlandi, "
            "lekin faollashtirishda xato yuz berdi. Qo'lda tekshiring."
        )
        return {"status": "no_match", "amount": amount}

    await notify_founders(
        f"🤖✅ Avtomatik tasdiqlandi!\n\nBuyurtma: {order['order_code']}\n"
        f"Mijoz (tenant_id): {order['tenant_id']}\nSumma: {amount:,} so'm"
    )
    return {
        "status": "approved",
        "amount": amount,
        "order_code": order["order_code"],
        "tenant_id": order["tenant_id"],
    }
