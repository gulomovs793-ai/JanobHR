"""Partner komissiyasini yechish arizalari va kechikish bonuslari.

Bu modul hamkorlar uchun pul yechish arizasini xavfsiz qiladi:
- faqat real tasdiqlangan sale eventlardan balans hisoblaydi;
- bitta sale eventni pending/paid arizaga bog'lab, takror yechishni bloklaydi;
- founderga qaysi mijozdan qancha komissiya kelganini ko'rsatadi;
- 1/11/21 payout kunlari, yakshanba/bayram skip va 3 000 UZS kechikish bonusini hisoblaydi.
"""

import os
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
        due = date.fromisoformat(str(payout_due_date)[:10])
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


async def create_payout_request(partner_id: int, payment_details: str) -> dict:
    await init_partner_payout_db()
    payment_details = (payment_details or "").strip()[:800]
    if len(payment_details) < 6:
        return {"ok": False, "error": "Karta yoki to'lov ma'lumoti juda qisqa."}

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
                payment_details, status, payout_due_date, requested_at
            ) VALUES (?, ?, 0, ?, ?, 'pending', ?, ?)
            """,
            (partner_id, amount, amount, payment_details, due, now),
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
        due = date.fromisoformat(row["payout_due_date"][:10])
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
            await db.execute(
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
            await db.execute(
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
        await db.commit()
    return await get_payout_request(request_id, include_items=True)
