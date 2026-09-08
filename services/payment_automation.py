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

import asyncio
import hashlib
import logging
import random
import re
from datetime import datetime, timedelta, timezone

import aiosqlite

from config import MONTHLY_PRICE_SOM, ORDER_TTL_MINUTES, PAYMENT_CARD_NUMBER
from services import database
from services.plans import PUBLIC_PLAN_CODES, get_plan, get_plan_transition

logger = logging.getLogger("janob_hr_bot")

# Shared-card namespace: Janob HR generated amounts end in 6/7/8/9.
# O‘zbek Ovoz AI uses 1/2/3/4. The physical card stays the same.
_JANOBHR_AMOUNT_LAST_DIGITS = {6, 7, 8, 9}

_NOTIFY_EXCLUDE_KEYWORDS = [
    "spisan",
    "spisano",
    "spisanie",  # yechib olindi — bu CHIQUVCHI tranzaksiya
    "otmen",
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

_NON_PAYMENT_SUMMARY_KEYWORDS = (
    "umumiy balans",
    "общий баланс",
    "balance summary",
)


def looks_like_non_payment_summary(text: str) -> bool:
    """CardXabarBot'ning balans/kartalar ro'yxati kabi ma'lumot xabarlarini
    haqiqiy to'lov bildirishnomasidan ajratadi."""
    raw = text or ""
    t = raw.lower()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    has_incoming_amount = any(re.match(r"^(\+|➕)", line) for line in lines)

    # Haqiqiy kirimda aniq "+" summa qatori bo'lsa, summary kalit so'zlari
    # tasodifan uchrasa ham to'lovni rad etmaymiz.
    if has_incoming_amount:
        return False

    if any(keyword in t for keyword in _NON_PAYMENT_SUMMARY_KEYWORDS):
        return True

    # CardXabarBot'ning karta ro'yxati formati: bir xabarda "Karta:" va
    # "Bank:" bloklari keladi. Bu tranzaksiya emas, hisob ma'lumoti.
    has_card_list = any(re.search(r"\b(?:karta|card)\s*:", line, re.IGNORECASE) for line in lines)
    has_bank_list = any(re.search(r"\b(?:bank)\s*:", line, re.IGNORECASE) for line in lines)
    return bool(has_card_list and has_bank_list)


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
    if looks_like_non_payment_summary(raw):
        return None

    for line in raw.splitlines():
        t = line.strip()
        if not re.match(r"^(\+|➕)", t):
            continue
        n = _extract_amount(t)
        if n is not None:
            return n

    for line in raw.splitlines():
        t = line.strip()
        if re.search(
            r"balans|balance|dostupno|ostatok|umumiy balans|общий баланс|💵|💰",
            t,
            re.IGNORECASE,
        ):
            continue
        n = _extract_amount(t)
        if n is not None:
            return n

    # Butun xabar bo'yicha fallback qilmaymiz: u ko'p qatorli balans/karta
    # ro'yxatidan noto'g'ri summani ushlab qolishi mumkin.
    return None


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


_PAYMENT_OFFSET_MAX = 1999
_AMOUNT_RESERVATION_HOURS = 24


async def _expire_stale_payment_orders(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    try:
        async with aiosqlite.connect(database.SQLITE_PATH, timeout=5) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                "UPDATE payment_orders SET status='expired', "
                "decided_at=COALESCE(decided_at, ?) "
                "WHERE status='awaiting_payment' AND expires_at<=?",
                (now_iso, now_iso),
            )
            await db.commit()
    except aiosqlite.OperationalError as exc:
        # Unit tests and first-start recovery may call this before init_db.
        # A real initialized production DB always has payment_orders.
        if "no such table" not in str(exc).lower():
            raise


async def _recent_non_live_orders(amount: int) -> list[dict]:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=_AMOUNT_RESERVATION_HOURS)
    ).isoformat()
    async with aiosqlite.connect(database.SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE amount=? AND created_at>=? "
            "AND status IN ('expired','cancelled','approved','needs_review') "
            "ORDER BY id DESC",
            (amount, cutoff),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def _handle_late_or_duplicate_payment(amount: int, notify_founders) -> dict | None:
    recent = await _recent_non_live_orders(amount)
    if not recent:
        return None

    # Amounts are reserved for 24h, so a recent approved order cannot belong to
    # a new customer. Treat a repeated bank notification as duplicate, not money
    # for a different tenant.
    if any(order["status"] == "approved" for order in recent):
        return {"status": "duplicate", "amount": amount}

    unresolved = [
        order for order in recent if order["status"] in {"expired", "cancelled", "needs_review"}
    ]
    if len(unresolved) == 1:
        order = unresolved[0]
        await database.mark_payment_order_needs_review(
            order["id"], "To'lov order muddati/bekor qilingandan keyin keldi"
        )
        await notify_founders(
            f"⚠️ Kechikkan to'lov: {amount:,} so'm. "
            f"Buyurtma {order['order_code']} endi avtomatik yoqilmadi; qo'lda tekshiring."
        )
        return {"status": "needs_review", "amount": amount}

    if unresolved:
        await notify_founders(
            f"⚠️ Kechikkan/noaniq to'lov: {amount:,} so'm bir nechta eski "
            "buyurtmaga mos keldi. Qo'lda tekshiring."
        )
        return {"status": "ambiguous", "amount": amount}
    return None


async def create_payment_order(
    tenant_id: int,
    base_amount: int | None = None,
    *,
    plan_code: str = "start",
    billing_months: int = 1,
    attribution: dict | None = None,
) -> dict:
    """Create an order atomically and reserve its exact amount for 24 hours.

    ``BEGIN IMMEDIATE`` serializes competing writers, eliminating the old
    check-then-insert race. Expired/cancelled/approved recent amounts stay
    reserved so a delayed bank notification can never activate a different
    customer's newly-created order.
    """
    try:
        base_amount = int(MONTHLY_PRICE_SOM if base_amount is None else base_amount)
        billing_months = int(billing_months)
    except (TypeError, ValueError) as exc:
        raise ValueError("To'lov summasi yoki muddati noto'g'ri") from exc
    plan_code = str(plan_code or "").strip().lower()
    if plan_code not in PUBLIC_PLAN_CODES:
        raise ValueError("Noto'g'ri tarif")
    plan = get_plan(plan_code)
    # The catalogue amount and partner commission are monthly amounts.  Until
    # a separate multi-month invoice/pricing flow exists, accepting a larger
    # month count here would let a caller pay once and receive several months.
    # Historical orders are still activated with their stored month count by
    # ``database.activate_subscription_for_order``; this guard applies only
    # to newly-created orders.
    if billing_months != 1:
        raise ValueError("Hozircha faqat 1 oylik to'lov buyurtmasi mavjud")
    if not 0 < base_amount <= plan.price:
        raise ValueError("To'lov summasi tarifga mos emas")

    if attribution and attribution.get("has_partner"):
        from services import partner_database as pdb

        # Schema creation happens before the core payment transaction. The
        # attribution row itself is then inserted by the same SQLite connection
        # below, so a crash cannot leave an order without its partner identity.
        await pdb.init_partner_db()

    for attempt in range(4):
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_at = (now + timedelta(minutes=ORDER_TTL_MINUTES)).isoformat()
        reservation_cutoff = (
            now - timedelta(hours=_AMOUNT_RESERVATION_HOURS)
        ).isoformat()

        try:
            async with aiosqlite.connect(database.SQLITE_PATH, timeout=10) as db:
                db.row_factory = aiosqlite.Row
                await db.execute("PRAGMA busy_timeout=10000")
                await db.execute("BEGIN IMMEDIATE")

                await db.execute(
                    "UPDATE payment_orders SET status='expired', "
                    "decided_at=COALESCE(decided_at, ?) "
                    "WHERE status='awaiting_payment' AND expires_at<=?",
                    (now_iso, now_iso),
                )
                await db.execute(
                    "UPDATE payment_orders SET status='cancelled', decided_at=? "
                    "WHERE tenant_id=? AND status='awaiting_payment'",
                    (now_iso, tenant_id),
                )

                cursor = await db.execute(
                    "SELECT amount FROM payment_orders WHERE created_at>=?",
                    (reservation_cutoff,),
                )
                reserved = {int(row[0]) for row in await cursor.fetchall()}

                offsets = [
                    offset
                    for offset in range(1, _PAYMENT_OFFSET_MAX + 1)
                    if (base_amount + offset) % 10 in _JANOBHR_AMOUNT_LAST_DIGITS
                ]
                random.shuffle(offsets)
                amount = next(
                    (base_amount + offset for offset in offsets if base_amount + offset not in reserved),
                    None,
                )
                if amount is None:
                    await db.rollback()
                    raise RuntimeError(
                        "Janob HR uchun 24 soatlik noyob to'lov summalari band."
                    )

                order_code = _new_order_code()
                cursor = await db.execute(
                    "INSERT INTO payment_orders "
                    "(tenant_id, order_code, base_amount, amount, plan_code, billing_months, "
                    "status, created_at, expires_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_payment', ?, ?)",
                    (
                        tenant_id,
                        order_code,
                        base_amount,
                        amount,
                        plan_code,
                        billing_months,
                        now_iso,
                        expires_at,
                    ),
                )
                if attribution and attribution.get("has_partner"):
                    from services import partner_database as pdb

                    await pdb._attach_payment_attribution_in_transaction(
                        db,
                        cursor.lastrowid,
                        tenant_id,
                        attribution,
                        order_amount=amount,
                    )
                await db.execute(
                    "UPDATE business_leads SET status='payment', updated_at=? "
                    "WHERE tenant_id=? AND status NOT IN ('lost', 'customer')",
                    (now_iso, tenant_id),
                )
                await db.commit()
                return {
                    "id": cursor.lastrowid,
                    "order_code": order_code,
                    "base_amount": base_amount,
                    "amount": amount,
                    "expires_at": expires_at,
                    "plan_code": plan_code,
                    "billing_months": billing_months,
                }
        except aiosqlite.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 3:
                raise
            await asyncio.sleep(0.05 * (attempt + 1))
        except aiosqlite.IntegrityError:
            if attempt == 3:
                raise
            await asyncio.sleep(0)

    raise RuntimeError("To'lov buyurtmasini yaratib bo'lmadi")


async def reconcile_approved_orders(
    activate_tenant,
    *,
    notify_founders=None,
    limit: int = 50,
) -> dict:
    """Recover approved payments interrupted between approval and activation.

    The payment notification is intentionally recorded before external webhook
    provisioning. If Render restarts at that exact point, the bank message will
    not be delivered again; this recovery pass closes that gap safely using the
    order-level activation marker.
    """
    orders = await database.list_approved_orders_without_subscription(limit)
    recovered = 0
    failed = 0
    partner_recovered = 0
    from services import partner_database as pdb

    for order in orders:
        try:
            result = await activate_tenant(order["tenant_id"])
            if not result or not result.get("ok"):
                raise RuntimeError(
                    (result or {}).get("error", "Tenantni faollashtirib bo'lmadi")
                )
            activation = await database.activate_subscription_for_order(order["id"])
            if activation.get("ok"):
                recovered += 1
            sale = await pdb.finalize_sale_for_order(
                order["id"], actual_amount=order["amount"]
            )
            if sale:
                partner_recovered += 1
        except Exception as exc:
            failed += 1
            logger.exception(
                "Approved order recovery ishlamadi: order=%s", order.get("order_code")
            )
            if notify_founders:
                try:
                    await notify_founders(
                        f"🚨 Recovery kerak: {order.get('order_code')} to'lovi tasdiqlangan, "
                        f"lekin tarif hali yoqilmadi. Xato: {str(exc)[:180]}"
                    )
                except Exception:
                    logger.exception("Founderga payment recovery xabari yuborilmadi")
    return {
        "found": len(orders),
        "recovered": recovered,
        "partner_recovered": partner_recovered,
        "failed": failed,
    }


async def run_approved_order_recovery_forever(
    activate_tenant,
    *,
    notify_founders=None,
    interval_seconds: int = 300,
) -> None:
    await asyncio.sleep(15)
    while True:
        try:
            result = await reconcile_approved_orders(
                activate_tenant,
                notify_founders=notify_founders,
            )
            if result["found"]:
                logger.info("Approved payment recovery: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Approved payment recovery loop ishlamadi")
        try:
            # Activation can succeed while partner finalization is interrupted.
            # Keep this retry independent from subscription recovery so a
            # transient partner-table/DB error cannot hide payment recovery.
            from services import partner_database as pdb

            partner_result = await pdb.reconcile_approved_partner_sales()
            if partner_result["found"]:
                logger.info("Partner sale recovery: %s", partner_result)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Partner sale recovery loop ishlamadi")
        try:
            from userbot import _notify_tenant_payment_approved

            for order in await database.list_unnotified_approved_orders():
                try:
                    await _notify_tenant_payment_approved(order)
                except Exception:
                    logger.exception("Customer payment receipt recovery failed: order=%s", order["order_code"])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Customer payment receipt recovery loop failed")
        await asyncio.sleep(max(30, int(interval_seconds)))


async def handle_payment_notification(
    raw_text: str, notify_founders, activate_tenant, *, notify_no_match: bool = True
) -> dict:
    """Userbot orqali kelgan xom bildirishnoma matnini qayta ishlaydi.

    `notify_founders(text: str)` — asoschilarga xabar yuborish uchun async chaqiruv.
    `activate_tenant(tenant_id: int)` — mos buyurtma topilganda tenantni
    faollashtiruvchi async chaqiruv (webhooklarni o'rnatish va h.k.).
    """
    text = (raw_text or "").strip()
    if not text:
        return {"status": "no_amount"}

    if looks_like_non_payment_summary(text):
        logger.info("[to'lov] balans/karta ma'lumoti, e'tiborsiz qoldirildi.")
        return {"status": "ignored_non_payment"}

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
            "Agar bu SIZNING to'lovingiz bo'lsa, PAYMENT_CARD_NUMBER Render'da "
            "noto'g'ri sozlangan bo'lishi mumkin."
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

    await _expire_stale_payment_orders()
    candidates = await database.get_open_payment_orders_by_amount(amount)

    if not candidates:
        late = await _handle_late_or_duplicate_payment(amount, notify_founders)
        if late is not None:
            return late
        if notify_no_match:
            await notify_founders(
                f"⚠️ Noma'lum kirim: {amount:,} so'm\n"
                "Ochiq buyurtmaga mos kelmadi."
            )
        logger.info("[to'lov] Mos kelmadi: amount=%s", amount)
        return {"status": "no_match", "amount": amount}

    if len(candidates) > 1:
        codes = ", ".join(o["order_code"] for o in candidates)
        await notify_founders(
            f"⚠️ Noaniq to'lov: {amount:,} so'm bir nechta buyurtmaga mos keldi: {codes}\n\nQo'lda tekshiring."
        )
        return {"status": "ambiguous", "amount": amount}

    order = candidates[0]

    usage = await database.get_subscription_usage(order["tenant_id"])
    transition = get_plan_transition(
        usage["plan"].code,
        order.get("plan_code", "start"),
        current_expired=usage["expired"],
    )
    if transition == "blocked":
        await database.mark_payment_order_needs_review(
            order["id"], "Faol yuqori tarif sabab past tarif avtomatik yoqilmadi"
        )
        await notify_founders(
            f"⚠️ {order['order_code']} to'lovi aniqlandi, lekin mijozda "
            f"{usage['plan'].name} tarifi hali faol. Past tarif avtomatik yoqilmadi; "
            "to'lovni qo'lda tekshiring yoki qaytaring."
        )
        return {"status": "needs_review", "amount": amount}

    # --- Atomik tasdiqlash (parallel bildirishnoma ikki marta faollashtirmasligi uchun) ---
    won = await database.try_approve_payment_order(order["id"])
    if not won:
        return {"status": "duplicate", "amount": amount}

    try:
        activation = await activate_tenant(order["tenant_id"])
        if not activation or not activation.get("ok"):
            error = (activation or {}).get("error", "Noma'lum faollashtirish xatosi")
            raise RuntimeError(error)
        activation_record = await database.activate_subscription_for_order(order["id"])
        if not activation_record.get("ok"):
            raise RuntimeError("Tarifni atomik faollashtirish amalga oshmadi")
    except Exception:
        logger.exception(
            "Tolov aniqlandi, lekin tenantni faollashtirishda xato (order=%s).",
            order["order_code"],
        )
        await database.mark_payment_order_needs_review(
            order["id"], str(text[:200]), keep_approved=True
        )
        await notify_founders(
            f"🚨 Avtomatik tasdiqlash xatosi: {order['order_code']} to'lovi aniqlandi, "
            "lekin faollashtirishda xato yuz berdi. Qo'lda tekshiring."
        )
        return {"status": "needs_review", "amount": amount}

    partner_sale = None
    partner_failed = False
    from services import partner_database as pdb
    for attempt in range(3):
        try:
            partner_sale = await pdb.finalize_sale_for_order(
                order["id"], actual_amount=amount
            )
            partner_failed = False
            break
        except Exception:
            partner_failed = True
            logger.exception(
                "Partner komissiyasini yakunlashda xato (order=%s, attempt=%s).",
                order["order_code"],
                attempt + 1,
            )
            if attempt < 2:
                await asyncio.sleep(0.2)
    if partner_failed:
        await notify_founders(
            f"⚠️ {order['order_code']} uchun partner komissiyasi vaqtincha yozilmadi. "
            "To'lov tasdiqlangan, reconcile avtomatik qayta urinadi."
        )

    partner_note = ""
    if partner_sale:
        try:
            from services import partner_database as pdb

            partner_note = (
                "\n\n🤝 Partner komissiyasi yozildi: "
                f"{pdb.format_uzs(partner_sale['commission_amount'])}"
            )
            if partner_sale.get("promo_code"):
                discount_label = (
                    f"{pdb.format_uzs(partner_sale.get('discount_value') or partner_sale.get('discount_amount') or 0)}"
                    if partner_sale.get("discount_type") == "amount"
                    else f"{partner_sale.get('discount_percent', 0)}%"
                )
                partner_note += (
                    f"\nPromo: {partner_sale['promo_code']} "
                    f"(-{discount_label})"
                )
        except (KeyError, TypeError, ValueError):
            partner_note = "\n\n🤝 Partner komissiyasi yozildi."

    await notify_founders(
        f"🤖✅ Avtomatik tasdiqlandi!\n\nBuyurtma: {order['order_code']}\n"
        f"Mijoz (tenant_id): {order['tenant_id']}\nSumma: {amount:,} so'm"
        f"{partner_note}"
    )
    result = {
        "status": "approved",
        "amount": amount,
        "order_code": order["order_code"],
        "tenant_id": order["tenant_id"],
    }
    if partner_sale:
        result["partner_commission"] = partner_sale.get("commission_amount")
        result["partner_promo_code"] = partner_sale.get("promo_code") or ""
    return result
