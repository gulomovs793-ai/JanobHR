"""Partner komissiyasini yechish arizalari va kechikish bonuslari.

Bu modul hamkorlar uchun pul yechish arizasini xavfsiz qiladi:
- faqat real tasdiqlangan sale eventlardan balans hisoblaydi;
- bitta sale eventni pending/paid arizaga bog'lab, takror yechishni bloklaydi;
- founderga qaysi mijozdan qancha komissiya kelganini ko'rsatadi;
- 1/11/21 payout kunlari, yakshanba/bayram skip va 3 000 UZS kechikish bonusini hisoblaydi.
"""

import os
import re
from datetime import date, datetime, timedelta, timezone

import aiosqlite

from config import SQLITE_PATH

UZ_TZ = timezone(timedelta(hours=5))
PAYOUT_DAYS = (1, 11, 21)
DELAY_BONUS_PER_DAY = 3_000
DELAY_BONUS_MAX_DAYS = 7


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _local_date(value: str | None) -> date | None:
    dt = _parse_dt(value)
    if not dt:
        return None
    return dt.astimezone(UZ_TZ).date()


def _configured_holidays() -> set[date]:
    """Render env: PARTNER_PAYOUT_HOLIDAYS=2026-03-21,2026-09-01"""
    result: set[date] = set()
    for raw in (os.getenv("PARTNER_PAYOUT_HOLIDAYS") or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            result.add(date.fromisoformat(raw))
        except ValueError:
            continue
    return result


def is_skipped_payout_day(day: date) -> bool:
    return day.weekday() == 6 or day in _configured_holidays()


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def _safe_date(year: int, month: int, day: int) -> date:
    # payout kunlari 1/11/21 bo'lgani uchun har oyda mavjud.
    return date(year, month, day)


def adjust_payout_date(day: date) -> date:
    while is_skipped_payout_day(day):
        day += timedelta(days=1)
    return day


def next_payout_date(from_dt: datetime | None = None) -> date:
    local_today = (from_dt or datetime.now(timezone.utc)).astimezone(UZ_TZ).date()
    year, month = local_today.year, local_today.month

    for _ in range(15):
        for payout_day in PAYOUT_DAYS:
            due = adjust_payout_date(_safe_date(year, month, payout_day))
            if due >= local_today:
                return due
        year, month = _next_month(year, month)

    # Amalda bu yerga kelmaydi.
    return adjust_payout_date(_safe_date(local_today.year, local_today.month, 21))


def count_delay_days(due_date: date, now_dt: datetime | None = None) -> int:
    today = (now_dt or datetime.now(timezone.utc)).astimezone(UZ_TZ).date()
    if today <= due_date:
        return 0
    days = 0
    current = due_date + timedelta(days=1)
    while current <= today and days < DELAY_BONUS_MAX_DAYS:
        if not is_skipped_payout_day(current):
            days += 1
        current += timedelta(days=1)
    return days


def payout_delay_info(payout_due_date: str | date | None, now_dt: datetime | None = None) -> dict:
    if isinstance(payout_due_date, date):
        due = payout_due_date
    elif payout_due_date:
        try:
            due = date.fromisoformat(str(payout_due_date)[:10])
        except (TypeError, ValueError):
            # A malformed legacy row must not stop the reminder worker or
            # prevent a partner from seeing their balance. Re-anchor it to the
            # next valid payout date and let the founder review the row.
            due = next_payout_date(now_dt)
    else:
        due = next_payout_date(now_dt)
    delay_days = count_delay_days(due, now_dt)
    bonus_amount = delay_days * DELAY_BONUS_PER_DAY
    return {
        "due_date": due.isoformat(),
        "delay_days": delay_days,
        "bonus_amount": bonus_amount,
    }


async def init_partner_payout_db() -> None:
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS partner_payout_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL,
                requested_amount INTEGER NOT NULL DEFAULT 0,
                bonus_amount INTEGER NOT NULL DEFAULT 0,
                total_amount INTEGER NOT NULL DEFAULT 0,
                payment_details TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                payout_due_date TEXT NOT NULL,
                requested_at TEXT NOT NULL,
                paid_at TEXT,
                rejected_at TEXT,
                decided_at TEXT,
                decided_by INTEGER,
                note TEXT,
                founder_notified_at TEXT,
                last_reminded_at TEXT,
                reminder_count INTEGER NOT NULL DEFAULT 0,
                payout_full_name TEXT,
                payout_card_number TEXT,
                receipt_telegram_username TEXT,
                partner_notified_at TEXT,
                partner_notification_last_attempt_at TEXT,
                partner_notification_attempts INTEGER NOT NULL DEFAULT 0,
                partner_notification_last_error TEXT,
                FOREIGN KEY(partner_id) REFERENCES partners(id)
            );

            CREATE TABLE IF NOT EXISTS partner_payout_request_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payout_request_id INTEGER NOT NULL,
                referral_event_id INTEGER NOT NULL,
                tenant_id INTEGER,
                company_name TEXT,
                plan_code TEXT,
                sale_amount INTEGER NOT NULL DEFAULT 0,
                commission_amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(payout_request_id) REFERENCES partner_payout_requests(id),
                FOREIGN KEY(referral_event_id) REFERENCES partner_referral_events(id)
            );

            CREATE INDEX IF NOT EXISTS idx_partner_payout_partner_status
                ON partner_payout_requests(partner_id, status, requested_at);
            CREATE INDEX IF NOT EXISTS idx_partner_payout_status_due
                ON partner_payout_requests(status, payout_due_date, last_reminded_at);
            CREATE INDEX IF NOT EXISTS idx_partner_payout_items_request
                ON partner_payout_request_items(payout_request_id);
            CREATE INDEX IF NOT EXISTS idx_partner_payout_items_event
                ON partner_payout_request_items(referral_event_id);
            """
        )
        # Existing Render disks already contain this table. Keep the migration
        # additive so old payout requests remain readable and payable.
        for column, definition in (
            ("payout_full_name", "TEXT"),
            ("payout_card_number", "TEXT"),
            ("receipt_telegram_username", "TEXT"),
            ("partner_notified_at", "TEXT"),
            ("partner_notification_last_attempt_at", "TEXT"),
            ("partner_notification_attempts", "INTEGER NOT NULL DEFAULT 0"),
            ("partner_notification_last_error", "TEXT"),
        ):
            try:
                await db.execute(
                    f"ALTER TABLE partner_payout_requests ADD COLUMN {column} {definition}"
                )
            except aiosqlite.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        await db.commit()


def _enrich_request(row: dict) -> dict:
    delay = payout_delay_info(row.get("payout_due_date"))
    requested_amount = int(row.get("requested_amount") or 0)
    row["delay_days"] = delay["delay_days"]
    row["bonus_amount"] = delay["bonus_amount"]
    row["total_amount"] = requested_amount + delay["bonus_amount"]
    row["payout_due_date"] = delay["due_date"]
    return row


async def get_partner_balance(partner_id: int) -> dict:
    await init_partner_payout_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT COUNT(*) AS sale_count,
                   COALESCE(SUM(commission_amount), 0) AS earned
            FROM partner_referral_events
            WHERE partner_id=? AND event_type='sale' AND COALESCE(commission_amount, 0)>0
            """,
            (partner_id,),
        )
        earned_row = await cur.fetchone()
        cur = await db.execute(
            """
            SELECT COALESCE(SUM(i.commission_amount), 0) AS reserved
            FROM partner_payout_request_items i
            JOIN partner_payout_requests r ON r.id=i.payout_request_id
            WHERE r.partner_id=? AND r.status='pending'
            """,
            (partner_id,),
        )
        reserved_row = await cur.fetchone()
        cur = await db.execute(
            """
            SELECT COALESCE(SUM(i.commission_amount), 0) AS paid
            FROM partner_payout_request_items i
            JOIN partner_payout_requests r ON r.id=i.payout_request_id
            WHERE r.partner_id=? AND r.status='paid'
            """,
            (partner_id,),
        )
        paid_row = await cur.fetchone()
        cur = await db.execute(
            """
            SELECT r.*, p.full_name AS partner_name, p.username AS partner_username,
                   p.telegram_user_id AS partner_telegram_user_id
            FROM partner_payout_requests r
            JOIN partners p ON p.id=r.partner_id
            WHERE r.partner_id=? AND r.status='pending'
            ORDER BY r.id DESC LIMIT 1
            """,
            (partner_id,),
        )
        active = await cur.fetchone()

    earned = int(earned_row["earned"] or 0)
    reserved = int(reserved_row["reserved"] or 0)
    paid = int(paid_row["paid"] or 0)
    return {
        "sale_count": int(earned_row["sale_count"] or 0),
        "earned": earned,
        "reserved": reserved,
        "paid": paid,
        "available": max(0, earned - reserved - paid),
        "active_request": _enrich_request(dict(active)) if active else None,
    }


async def _unpaid_sales_for_partner(db: aiosqlite.Connection, partner_id: int) -> list[dict]:
    cur = await db.execute(
        """
        SELECT e.id AS sale_event_id,
               e.tenant_id,
               e.plan_code,
               e.amount AS sale_amount,
               e.commission_amount,
               e.created_at AS sale_created_at,
               COALESCE(t.company_name, 'Mijoz') AS company_name,
               COALESCE(t.contact_name, '') AS contact_name,
               COALESCE(t.contact_phone, '') AS contact_phone,
               COALESCE(t.contact_username, '') AS contact_username
        FROM partner_referral_events e
        LEFT JOIN tenants t ON t.id=e.tenant_id
        WHERE e.partner_id=?
          AND e.event_type='sale'
          AND COALESCE(e.commission_amount, 0)>0
          AND NOT EXISTS (
              SELECT 1
              FROM partner_payout_request_items i
              JOIN partner_payout_requests r ON r.id=i.payout_request_id
              WHERE i.referral_event_id=e.id
                AND r.status IN ('pending', 'paid')
          )
        ORDER BY e.created_at ASC, e.id ASC
        """,
        (partner_id,),
    )
    return [dict(row) for row in await cur.fetchall()]


async def get_payout_request_items(request_id: int) -> list[dict]:
    await init_partner_payout_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM partner_payout_request_items
            WHERE payout_request_id=?
            ORDER BY created_at ASC, id ASC
            """,
            (request_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_payout_request(request_id: int, *, include_items: bool = True) -> dict | None:
    await init_partner_payout_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT r.*, p.full_name AS partner_name, p.username AS partner_username,
                   p.phone AS partner_phone,
                   p.telegram_user_id AS partner_telegram_user_id
            FROM partner_payout_requests r
            JOIN partners p ON p.id=r.partner_id
            WHERE r.id=? LIMIT 1
            """,
            (request_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        result = _enrich_request(dict(row))
        if include_items:
            cur = await db.execute(
                """
                SELECT * FROM partner_payout_request_items
                WHERE payout_request_id=?
                ORDER BY created_at ASC, id ASC
                """,
                (request_id,),
            )
            result["items"] = [dict(item) for item in await cur.fetchall()]
        return result


def normalize_payout_full_name(value: str) -> str:
    return " ".join((value or "").strip().split())[:120]


def normalize_card_number(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def normalize_receipt_username(value: str) -> str:
    username = (value or "").strip().replace(" ", "")
    if username and not username.startswith("@"):
        username = "@" + username
    return username


def validate_payout_details(
    full_name: str, card_number: str, receipt_username: str
) -> tuple[str, str, str, str | None]:
    """Normalize payout identity/payment fields before one DB transaction."""
    clean_name = normalize_payout_full_name(full_name)
    clean_card = normalize_card_number(card_number)
    clean_username = normalize_receipt_username(receipt_username)
    if len(clean_name) < 5 or len(clean_name.split()) < 2:
        return clean_name, clean_card, clean_username, "Ism va familiyangizni to'liq kiriting."
    if len(clean_card) not in {16, 17, 18, 19}:
        return clean_name, clean_card, clean_username, "Karta raqami 16–19 ta raqamdan iborat bo'lishi kerak."
    if not re.fullmatch(r"@[A-Za-z0-9_]{5,32}", clean_username):
        return clean_name, clean_card, clean_username, "Telegram username @ bilan, masalan @janobhr bo'lishi kerak."
    return clean_name, clean_card, clean_username, None


async def create_payout_request(
    partner_id: int,
    full_name: str,
    card_number: str | None = None,
    receipt_username: str | None = None,
    *,
    payment_details: str | None = None,
) -> dict:
    await init_partner_payout_db()
    legacy_details = payment_details is not None or (
        card_number is None and receipt_username is None
    )
    if legacy_details:
        # Backward compatibility for already-integrated callers. New requests
        # always use the three explicit fields below.
        payment_details = (payment_details or full_name or "").strip()[:800]
        if len(payment_details) < 6:
            return {"ok": False, "error": "Karta yoki to'lov ma'lumoti juda qisqa."}
        payout_full_name = ""
        payout_card_number = ""
        receipt_telegram_username = ""
    else:
        (
            payout_full_name,
            payout_card_number,
            receipt_telegram_username,
            validation_error,
        ) = validate_payout_details(full_name, card_number or "", receipt_username or "")
        if validation_error:
            return {"ok": False, "error": validation_error}
        payment_details = (
            f"Ism: {payout_full_name}; Karta: {payout_card_number}; "
            f"Chek uchun: {receipt_telegram_username}"
        )[:800]

    now = _now()
    due = next_payout_date().isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=10) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("BEGIN IMMEDIATE")

        cur = await db.execute(
            "SELECT * FROM partners WHERE id=? AND status='approved' LIMIT 1",
            (partner_id,),
        )
        partner = await cur.fetchone()
        if not partner:
            await db.rollback()
            return {"ok": False, "error": "Hamkor tasdiqlanmagan."}

        cur = await db.execute(
            """
            SELECT id FROM partner_payout_requests
            WHERE partner_id=? AND status='pending'
            ORDER BY id DESC LIMIT 1
            """,
            (partner_id,),
        )
        active = await cur.fetchone()
        if active:
            await db.rollback()
            return {
                "ok": False,
                "error": f"Sizda #{active['id']} raqamli yechish arizasi hali yopilmagan.",
            }

        sales = await _unpaid_sales_for_partner(db, partner_id)
        amount = sum(int(s.get("commission_amount") or 0) for s in sales)
        if amount <= 0:
            await db.rollback()
            return {"ok": False, "error": "Hozir yechish mumkin bo'lgan komissiya yo'q."}

        cur = await db.execute(
            """
            INSERT INTO partner_payout_requests(
                partner_id, requested_amount, bonus_amount, total_amount,
                payment_details, status, payout_due_date, requested_at,
                payout_full_name, payout_card_number, receipt_telegram_username
            ) VALUES (?, ?, 0, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """,
            (
                partner_id,
                amount,
                amount,
                payment_details,
                due,
                now,
                payout_full_name,
                payout_card_number,
                receipt_telegram_username,
            ),
        )
        request_id = cur.lastrowid
        for sale in sales:
            await db.execute(
                """
                INSERT INTO partner_payout_request_items(
                    payout_request_id, referral_event_id, tenant_id, company_name,
                    plan_code, sale_amount, commission_amount, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    int(sale["sale_event_id"]),
                    sale.get("tenant_id"),
                    sale.get("company_name") or "Mijoz",
                    sale.get("plan_code") or "",
                    int(sale.get("sale_amount") or 0),
                    int(sale.get("commission_amount") or 0),
                    now,
                ),
            )
        await db.commit()

    request = await get_payout_request(request_id, include_items=True)
    assert request is not None
    request["ok"] = True
    return request


async def mark_payout_notified(request_id: int, *, first: bool = False) -> None:
    await init_partner_payout_db()
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        if first:
            await db.execute(
                "UPDATE partner_payout_requests SET founder_notified_at=COALESCE(founder_notified_at, ?) WHERE id=?",
                (now, request_id),
            )
        else:
            await db.execute(
                """
                UPDATE partner_payout_requests
                SET last_reminded_at=?, reminder_count=COALESCE(reminder_count, 0)+1
                WHERE id=?
                """,
                (now, request_id),
            )
        await db.commit()


async def claim_paid_payout_notification(
    request_id: int, *, retry_after_seconds: int = 300
) -> dict | None:
    """Claim one paid-request notification so concurrent workers cannot duplicate it."""
    await init_partner_payout_db()
    now = datetime.now(timezone.utc)
    retry_after = max(0, int(retry_after_seconds))
    cutoff = (now - timedelta(seconds=retry_after)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        cursor = await db.execute(
            """
            UPDATE partner_payout_requests
            SET partner_notification_last_attempt_at=?,
                partner_notification_attempts=COALESCE(partner_notification_attempts, 0)+1
            WHERE id=? AND status='paid' AND partner_notified_at IS NULL
              AND (partner_notification_last_attempt_at IS NULL
                   OR partner_notification_last_attempt_at <= ?)
            """,
            (now.isoformat(), request_id, cutoff),
        )
        if cursor.rowcount != 1:
            await db.rollback()
            return None
        await db.commit()
    return await get_payout_request(request_id, include_items=True)


async def mark_partner_payout_notified(
    request_id: int, *, error: str | None = None
) -> None:
    """Persist the result of the partner's paid/rejected payout notification."""
    await init_partner_payout_db()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        if error:
            await db.execute(
                """
                UPDATE partner_payout_requests
                SET partner_notification_last_error=?
                WHERE id=? AND status='paid'
                """,
                (str(error)[:500], request_id),
            )
        else:
            await db.execute(
                """
                UPDATE partner_payout_requests
                SET partner_notified_at=?, partner_notification_last_error=NULL
                WHERE id=? AND status='paid'
                """,
                (_now(), request_id),
            )
        await db.commit()


async def list_paid_payouts_needing_partner_notification(
    limit: int = 20, *, retry_after_seconds: int = 300
) -> list[dict]:
    """Return paid requests eligible for a safe partner-notification retry."""
    await init_partner_payout_db()
    limit = max(1, min(int(limit or 20), 100))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=max(0, int(retry_after_seconds)))
    ).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id FROM partner_payout_requests
            WHERE status='paid' AND partner_notified_at IS NULL
              AND (partner_notification_last_attempt_at IS NULL
                   OR partner_notification_last_attempt_at <= ?)
            ORDER BY id ASC LIMIT ?
            """,
            (cutoff, limit),
        )
        request_ids = [int(row["id"]) for row in await cursor.fetchall()]
    result: list[dict] = []
    for request_id in request_ids:
        request = await get_payout_request(request_id, include_items=True)
        if request:
            result.append(request)
    return result


async def list_payout_requests_needing_reminder(limit: int = 20) -> list[dict]:
    await init_partner_payout_db()
    today = datetime.now(timezone.utc).astimezone(UZ_TZ).date()
    result: list[dict] = []
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT r.*, p.full_name AS partner_name, p.username AS partner_username,
                   p.phone AS partner_phone,
                   p.telegram_user_id AS partner_telegram_user_id
            FROM partner_payout_requests r
            JOIN partners p ON p.id=r.partner_id
            WHERE r.status='pending'
            ORDER BY r.payout_due_date ASC, r.id ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(row) for row in await cur.fetchall()]

    for row in rows:
        due = payout_delay_info(row.get("payout_due_date"))["due_date"]
        due = date.fromisoformat(due)
        if due > today:
            continue
        last = _local_date(row.get("last_reminded_at"))
        if last == today:
            continue
        request = await get_payout_request(int(row["id"]), include_items=True)
        if request:
            result.append(request)
    return result


async def set_payout_request_status(
    request_id: int,
    status: str,
    *,
    decided_by: int | None = None,
    note: str = "",
) -> dict | None:
    if status not in {"paid", "rejected"}:
        raise ValueError("invalid payout status")
    request = await get_payout_request(request_id, include_items=False)
    if not request:
        return None
    now = _now()
    delay = payout_delay_info(request.get("payout_due_date"))
    total_amount = int(request.get("requested_amount") or 0) + int(delay["bonus_amount"])

    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        if status == "paid":
            cursor = await db.execute(
                """
                UPDATE partner_payout_requests
                SET status='paid', paid_at=?, decided_at=?, decided_by=?, note=?,
                    bonus_amount=?, total_amount=?
                WHERE id=? AND status='pending'
                """,
                (
                    now,
                    now,
                    decided_by,
                    note,
                    int(delay["bonus_amount"]),
                    total_amount,
                    request_id,
                ),
            )
        else:
            cursor = await db.execute(
                """
                UPDATE partner_payout_requests
                SET status='rejected', rejected_at=?, decided_at=?, decided_by=?, note=?,
                    bonus_amount=?, total_amount=?
                WHERE id=? AND status='pending'
                """,
                (
                    now,
                    now,
                    decided_by,
                    note,
                    int(delay["bonus_amount"]),
                    total_amount,
                    request_id,
                ),
            )
        # Two founder clicks or duplicate webhook deliveries must not send a
        # second success message or pay the same request twice.
        if cursor.rowcount != 1:
            await db.rollback()
            return None
        await db.commit()
    return await get_payout_request(request_id, include_items=True)
