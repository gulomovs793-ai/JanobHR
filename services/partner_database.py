"""Janob HR partner/referral tizimi uchun alohida SQLite qatlami.

Bu modul mavjud Janob HR bazasidan foydalanadi, lekin partner jadvallarini
mustaqil boshqaradi. Shu sabab asosiy tenant/application sxemasiga tegmaydi.
"""

import secrets
from datetime import datetime, timezone

import aiosqlite

from config import SQLITE_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_partner_db() -> None:
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.executescript(
            """
            CREATE TABLE IF NOT EXISTS partners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_user_id INTEGER NOT NULL UNIQUE,
                full_name TEXT,
                username TEXT,
                phone TEXT,
                role TEXT,
                has_business_clients INTEGER NOT NULL DEFAULT 0,
                client_band TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                referral_code TEXT UNIQUE,
                approved_at TEXT,
                rejected_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS partner_referral_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL,
                referred_telegram_user_id INTEGER,
                event_type TEXT NOT NULL,
                tenant_id INTEGER,
                plan_code TEXT,
                amount INTEGER,
                commission_amount INTEGER,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(partner_id) REFERENCES partners(id)
            );

            CREATE INDEX IF NOT EXISTS idx_partner_events_partner
                ON partner_referral_events(partner_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_partner_events_user
                ON partner_referral_events(referred_telegram_user_id, created_at);
            """
        )
        await db.commit()


async def get_partner_by_user_id(user_id: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM partners WHERE telegram_user_id=? LIMIT 1", (user_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_partner_by_code(code: str) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM partners WHERE referral_code=? AND status='approved' LIMIT 1",
            (code,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def upsert_application(
    *,
    user_id: int,
    full_name: str,
    username: str,
    phone: str,
    role: str,
    has_business_clients: bool,
    client_band: str,
) -> dict:
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        cur = await db.execute(
            "SELECT id, referral_code FROM partners WHERE telegram_user_id=? LIMIT 1",
            (user_id,),
        )
        existing = await cur.fetchone()
        if existing:
            await db.execute(
                """
                UPDATE partners
                SET full_name=?, username=?, phone=?, role=?, has_business_clients=?,
                    client_band=?, status='pending', rejected_at=NULL, updated_at=?
                WHERE telegram_user_id=?
                """,
                (
                    full_name,
                    username,
                    phone,
                    role,
                    int(has_business_clients),
                    client_band,
                    now,
                    user_id,
                ),
            )
        else:
            await db.execute(
                """
                INSERT INTO partners(
                    telegram_user_id, full_name, username, phone, role,
                    has_business_clients, client_band, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    user_id,
                    full_name,
                    username,
                    phone,
                    role,
                    int(has_business_clients),
                    client_band,
                    now,
                    now,
                ),
            )
        await db.commit()
    partner = await get_partner_by_user_id(user_id)
    assert partner is not None
    return partner


async def set_partner_status(partner_id: int, status: str) -> dict | None:
    if status not in {'approved', 'rejected'}:
        raise ValueError('invalid partner status')
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        cur = await db.execute("SELECT * FROM partners WHERE id=?", (partner_id,))
        row = await cur.fetchone()
        if not row:
            return None
        code = row['referral_code']
        if status == 'approved' and not code:
            while True:
                code = secrets.token_urlsafe(6).replace('-', '').replace('_', '')[:8].upper()
                c = await db.execute(
                    "SELECT 1 FROM partners WHERE referral_code=? LIMIT 1", (code,)
                )
                if not await c.fetchone():
                    break
        await db.execute(
            """
            UPDATE partners
            SET status=?, referral_code=?, approved_at=?, rejected_at=?, updated_at=?
            WHERE id=?
            """,
            (
                status,
                code,
                now if status == 'approved' else row['approved_at'],
                now if status == 'rejected' else None,
                now,
                partner_id,
            ),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM partners WHERE id=?", (partner_id,))
        updated = await cur.fetchone()
        return dict(updated) if updated else None


async def record_referral_click(partner_id: int, referred_user_id: int) -> bool:
    """Bir userning bir partner uchun takroriy startlarini bitta click deb hisoblaydi."""
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        cur = await db.execute(
            """
            SELECT 1 FROM partner_referral_events
            WHERE partner_id=? AND referred_telegram_user_id=? AND event_type='click'
            LIMIT 1
            """,
            (partner_id, referred_user_id),
        )
        if await cur.fetchone():
            return False
        await db.execute(
            """
            INSERT INTO partner_referral_events(
                partner_id, referred_telegram_user_id, event_type, created_at
            ) VALUES (?, ?, 'click', ?)
            """,
            (partner_id, referred_user_id, _now()),
        )
        await db.commit()
        return True


async def get_partner_stats(partner_id: int) -> dict:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT
                SUM(CASE WHEN event_type='click' THEN 1 ELSE 0 END) AS clicks,
                SUM(CASE WHEN event_type='trial' THEN 1 ELSE 0 END) AS trials,
                SUM(CASE WHEN event_type='sale' THEN 1 ELSE 0 END) AS sales,
                COALESCE(SUM(CASE WHEN event_type='sale' THEN commission_amount ELSE 0 END), 0) AS earned
            FROM partner_referral_events
            WHERE partner_id=?
            """,
            (partner_id,),
        )
        row = await cur.fetchone()
        return {
            'clicks': int(row['clicks'] or 0),
            'trials': int(row['trials'] or 0),
            'sales': int(row['sales'] or 0),
            'earned': int(row['earned'] or 0),
        }
