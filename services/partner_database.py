"""Janob HR partner/referral tizimi uchun alohida SQLite qatlami.

Bu modul mavjud Janob HR bazasidan foydalanadi, lekin partner jadvallarini
mustaqil boshqaradi. Shu sabab asosiy tenant/application sxemasiga tegmaydi.
"""

import json
import logging
import re
import secrets
from datetime import datetime, timezone

import aiosqlite

from config import SQLITE_PATH
from services.plans import get_plan

logger = logging.getLogger("janob_hr_partner")


PARTNER_COMMISSIONS = {
    "start": 99_000,
    "growth": 199_000,
    "business": 299_000,
}
ALLOWED_PROMO_DISCOUNTS = (0, 5, 10, 15, 20)
MAX_UNIVERSAL_PROMO_AMOUNT = min(PARTNER_COMMISSIONS.values())
MAX_UNIVERSAL_PROMO_PERCENT = min(
    int(PARTNER_COMMISSIONS[code] * 100 / get_plan(code).price)
    for code in PARTNER_COMMISSIONS
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_uzs(amount: int) -> str:
    return f"{int(amount):,}".replace(",", " ") + " UZS"


def _clean_promo_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())[:32]


def calculate_partner_payout(
    plan_code: str,
    discount_percent: int = 0,
    *,
    discount_type: str = "percent",
    discount_value: int | None = None,
) -> dict:
    plan = get_plan(plan_code)
    discount_type = discount_type if discount_type in {"percent", "amount"} else "percent"
    value = int(discount_value if discount_value is not None else discount_percent or 0)
    if value < 0 or (discount_type == "percent" and value > 100):
        raise ValueError("Promo chegirma noto'g'ri")
    base_commission = PARTNER_COMMISSIONS.get(plan.code, 0)
    discount_amount = round(plan.price * value / 100) if discount_type == "percent" else value
    if discount_amount > base_commission:
        raise ValueError(
            f"Chegirma {plan.name} uchun {format_uzs(base_commission)} komissiyadan oshmasligi kerak"
        )
    discounted_base_amount = max(0, plan.price - discount_amount)
    commission_amount = max(0, base_commission - discount_amount)
    return {
        "plan_code": plan.code,
        "plan_name": plan.name,
        "original_amount": int(plan.price),
        "discount_percent": value if discount_type == "percent" else 0,
        "discount_type": discount_type,
        "discount_value": value,
        "discount_amount": int(discount_amount),
        "discounted_base_amount": int(discounted_base_amount),
        "base_commission": int(base_commission),
        "commission_amount": int(commission_amount),
    }


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

            CREATE TABLE IF NOT EXISTS partner_promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                partner_id INTEGER NOT NULL,
                code TEXT NOT NULL UNIQUE,
                discount_percent INTEGER NOT NULL,
                discount_type TEXT NOT NULL DEFAULT 'percent',
                discount_value INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                plan_code TEXT NOT NULL DEFAULT 'all',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(partner_id) REFERENCES partners(id)
            );

            CREATE TABLE IF NOT EXISTS partner_tenant_attributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL UNIQUE,
                partner_id INTEGER NOT NULL,
                referred_telegram_user_id INTEGER,
                source TEXT NOT NULL DEFAULT 'referral_link',
                referral_code TEXT,
                promo_code TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(partner_id) REFERENCES partners(id)
            );

            CREATE TABLE IF NOT EXISTS partner_payment_attributions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_order_id INTEGER NOT NULL UNIQUE,
                tenant_id INTEGER NOT NULL,
                partner_id INTEGER NOT NULL,
                source TEXT NOT NULL,
                promo_code TEXT,
                plan_code TEXT,
                discount_percent INTEGER NOT NULL DEFAULT 0,
                discount_type TEXT NOT NULL DEFAULT 'percent',
                discount_value INTEGER NOT NULL DEFAULT 0,
                original_amount INTEGER NOT NULL DEFAULT 0,
                discounted_base_amount INTEGER NOT NULL DEFAULT 0,
                order_amount INTEGER NOT NULL DEFAULT 0,
                base_commission INTEGER NOT NULL DEFAULT 0,
                discount_amount INTEGER NOT NULL DEFAULT 0,
                commission_amount INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'awaiting_payment',
                created_at TEXT NOT NULL,
                finalized_at TEXT,
                FOREIGN KEY(partner_id) REFERENCES partners(id)
            );

            CREATE INDEX IF NOT EXISTS idx_partner_events_partner
                ON partner_referral_events(partner_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_partner_events_user
                ON partner_referral_events(referred_telegram_user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_partner_events_tenant
                ON partner_referral_events(tenant_id, event_type);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_partner_trial_once
                ON partner_referral_events(tenant_id, event_type)
                WHERE tenant_id IS NOT NULL AND event_type='trial';
            CREATE INDEX IF NOT EXISTS idx_partner_promo_partner
                ON partner_promo_codes(partner_id, status);
            CREATE INDEX IF NOT EXISTS idx_partner_tenant_partner
                ON partner_tenant_attributions(partner_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_partner_payment_partner
                ON partner_payment_attributions(partner_id, created_at);
            """
        )
        # Existing production SQLite databases predate fixed-sum promos.
        # Migrate them in place without dropping or recreating any data.
        cur = await db.execute("PRAGMA table_info(partner_promo_codes)")
        existing_columns = {row[1] for row in await cur.fetchall()}
        for name, definition in (
            ("discount_type", "TEXT NOT NULL DEFAULT 'percent'"),
            ("discount_value", "INTEGER NOT NULL DEFAULT 0"),
            ("expires_at", "TEXT"),
            ("plan_code", "TEXT NOT NULL DEFAULT 'all'"),
        ):
            if name not in existing_columns:
                await db.execute(f"ALTER TABLE partner_promo_codes ADD COLUMN {name} {definition}")
        cur = await db.execute("PRAGMA table_info(partner_payment_attributions)")
        payment_columns = {row[1] for row in await cur.fetchall()}
        for name, definition in (
            ("discount_type", "TEXT NOT NULL DEFAULT 'percent'"),
            ("discount_value", "INTEGER NOT NULL DEFAULT 0"),
            ("plan_code", "TEXT"),
        ):
            if name not in payment_columns:
                await db.execute(f"ALTER TABLE partner_payment_attributions ADD COLUMN {name} {definition}")
        await db.execute(
            "UPDATE partner_promo_codes SET discount_value=discount_percent "
            "WHERE discount_value=0 AND discount_percent!=0"
        )
        await db.commit()


async def get_partner_by_user_id(user_id: int) -> dict | None:
    await init_partner_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM partners WHERE telegram_user_id=? LIMIT 1", (user_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def list_partners(status: str | None = None, limit: int = 100) -> list[dict]:
    """Return partner applications for the founder-only review flow."""
    await init_partner_db()
    limit = max(1, min(int(limit or 100), 500))
    query = "SELECT * FROM partners"
    params: list[object] = []
    if status:
        query += " WHERE status=?"
        params.append(status)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(query, params)
        return [dict(row) for row in await cur.fetchall()]


async def get_partner(partner_id: int) -> dict | None:
    await init_partner_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM partners WHERE id=? LIMIT 1", (partner_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_partner_by_code(code: str) -> dict | None:
    await init_partner_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM partners WHERE UPPER(referral_code)=UPPER(?) AND status='approved' LIMIT 1",
            (_clean_promo_code(code),),
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
    await init_partner_db()
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
    await init_partner_db()
    if status not in {"approved", "rejected"}:
        raise ValueError("invalid partner status")
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        cur = await db.execute("SELECT * FROM partners WHERE id=?", (partner_id,))
        row = await cur.fetchone()
        if not row:
            return None
        code = row["referral_code"]
        if status == "approved" and not code:
            while True:
                code = secrets.token_urlsafe(6).replace("-", "").replace("_", "")[:8].upper()
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
                now if status == "approved" else row["approved_at"],
                now if status == "rejected" else None,
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
    await init_partner_db()
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


async def record_referral_trial(
    partner_id: int,
    referred_user_id: int,
    tenant_id: int,
    *,
    source: str = "referral_link",
    referral_code: str = "",
    promo_code: str = "",
) -> bool:
    """Referral orqali kelgan mijozni tenantga bog'laydi va trialni bir marta yozadi."""
    await init_partner_db()
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute(
            """
            INSERT OR IGNORE INTO partner_tenant_attributions(
                tenant_id, partner_id, referred_telegram_user_id, source,
                referral_code, promo_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, partner_id, referred_user_id, source, referral_code, promo_code, now),
        )
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO partner_referral_events(
                partner_id, referred_telegram_user_id, event_type, tenant_id,
                metadata, created_at
            ) VALUES (?, ?, 'trial', ?, ?, ?)
            """,
            (
                partner_id,
                referred_user_id,
                tenant_id,
                json.dumps({"source": source, "referral_code": referral_code, "promo_code": promo_code}, ensure_ascii=False),
                now,
            ),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_tenant_attribution(tenant_id: int) -> dict | None:
    await init_partner_db()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT a.*, p.full_name AS partner_name, p.username AS partner_username
            FROM partner_tenant_attributions a
            JOIN partners p ON p.id=a.partner_id
            WHERE a.tenant_id=? LIMIT 1
            """,
            (tenant_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def claim_tenant_attribution(
    tenant_id: int,
    partner_id: int,
    *,
    source: str,
    promo_code: str = "",
) -> dict | None:
    """Atomically bind a tenant to its first partner.

    A promo-only customer has no referral-link event to create this row. The
    first valid promo therefore claims the tenant inside an immediate SQLite
    transaction; a concurrent/different partner can never replace it later.
    """
    await init_partner_db()
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        cur = await db.execute(
            "SELECT * FROM partner_tenant_attributions WHERE tenant_id=? LIMIT 1",
            (tenant_id,),
        )
        current = await cur.fetchone()
        if current and int(current["partner_id"]) != int(partner_id):
            await db.rollback()
            return None
        if not current:
            await db.execute(
                "INSERT INTO partner_tenant_attributions("
                "tenant_id, partner_id, source, promo_code, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (tenant_id, partner_id, source, promo_code, now),
            )
        elif promo_code and not current["promo_code"]:
            await db.execute(
                "UPDATE partner_tenant_attributions SET promo_code=? WHERE tenant_id=?",
                (promo_code, tenant_id),
            )
        await db.commit()
        cur = await db.execute(
            "SELECT * FROM partner_tenant_attributions WHERE tenant_id=? LIMIT 1",
            (tenant_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def create_or_update_promo_code(
    partner_id: int,
    discount_value: int,
    *,
    discount_type: str = "percent",
    duration_days: int = 30,
    plan_code: str = "all",
) -> dict | None:
    """Create the partner's single active promo code with an expiry date."""
    await init_partner_db()
    discount_type = (discount_type or "percent").strip().lower()
    discount_value = int(discount_value)
    duration_days = int(duration_days)
    plan_code = (plan_code or "all").strip().lower()
    if discount_type not in {"percent", "amount"}:
        raise ValueError("Promo turi noto'g'ri")
    if discount_value <= 0 or (
        discount_type == "percent" and discount_value > MAX_UNIVERSAL_PROMO_PERCENT
    ) or (
        discount_type == "amount" and discount_value > MAX_UNIVERSAL_PROMO_AMOUNT
    ):
        raise ValueError("Promo qiymati noto'g'ri")
    if duration_days < 1 or duration_days > 365:
        raise ValueError("Promo muddati 1-365 kun bo'lishi kerak")
    if plan_code != "all" and plan_code not in {"start", "growth", "business"}:
        raise ValueError("Promo tarifi noto'g'ri")
    now = _now()
    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        cur = await db.execute(
            "SELECT * FROM partners WHERE id=? AND status='approved' LIMIT 1", (partner_id,)
        )
        partner = await cur.fetchone()
        if not partner or not partner["referral_code"]:
            return None
        code = _clean_promo_code(f"{partner['referral_code']}{secrets.token_hex(2).upper()}")
        await db.execute(
            "UPDATE partner_promo_codes SET status='inactive', updated_at=? WHERE partner_id=? AND status='active'",
            (now, partner_id),
        )
        await db.execute(
            """
            INSERT INTO partner_promo_codes(
                partner_id, code, discount_percent, discount_type, discount_value,
                expires_at, status, created_at, updated_at
                , plan_code
            ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                discount_percent=excluded.discount_percent,
                discount_type=excluded.discount_type,
                discount_value=excluded.discount_value,
                expires_at=excluded.expires_at,
                plan_code=excluded.plan_code,
                status='active',
                updated_at=excluded.updated_at
            """,
            (partner_id, code, 0 if discount_type == "amount" else discount_value,
             discount_type, discount_value, expires_at, now, now, plan_code),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT * FROM partner_promo_codes WHERE partner_id=? AND status='active' LIMIT 1",
            (partner_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_active_promo_code(code: str) -> dict | None:
    await init_partner_db()
    cleaned = _clean_promo_code(code)
    if not cleaned:
        return None
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT pc.*, p.full_name AS partner_name, p.username AS partner_username,
                   p.telegram_user_id AS partner_telegram_user_id
            FROM partner_promo_codes pc
            JOIN partners p ON p.id=pc.partner_id
            WHERE UPPER(pc.code)=UPPER(?) AND pc.status='active' AND p.status='approved'
              AND (pc.expires_at IS NULL OR pc.expires_at > ?)
            LIMIT 1
            """,
            (cleaned, _now()),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def prepare_payment_attribution(
    tenant_id: int,
    plan_code: str,
    *,
    promo_code: str | None = None,
) -> dict:
    """Billing order uchun hamkor/chegirma hisobini tayyorlaydi.

    Promo chegirma mijoz narxidan tushiriladi, lekin aynan shu summa partnerning
    komissiyasidan ayriladi. Janob HRning bazaviy tushumi shu modelda himoyalanadi.
    """
    await init_partner_db()
    cleaned_promo = _clean_promo_code(promo_code or "")
    tenant_attr = await get_tenant_attribution(tenant_id)

    if cleaned_promo:
        promo = await get_active_promo_code(cleaned_promo)
        if not promo:
            return {"ok": False, "error": "Promo kod topilmadi yoki faol emas."}
        if promo.get("plan_code") not in (None, "", "all", plan_code):
            return {
                "ok": False,
                "error": f"Bu promo kod faqat {promo['plan_code'].upper()} tarifi uchun amal qiladi.",
            }
        if tenant_attr and int(tenant_attr["partner_id"]) != int(promo["partner_id"]):
            return {
                "ok": False,
                "error": "Bu hisob allaqachon boshqa hamkor orqali kelgan. Boshqa promo kod ishlamaydi.",
            }
        if not tenant_attr:
            tenant_attr = await claim_tenant_attribution(
                tenant_id,
                int(promo["partner_id"]),
                source="promo_code",
                promo_code=promo["code"],
            )
            if not tenant_attr:
                return {
                    "ok": False,
                    "error": "Bu hisob boshqa hamkor bilan bog'langan. Boshqa promo kod ishlamaydi.",
                }
        payout = calculate_partner_payout(
            plan_code,
            int(promo["discount_percent"] or 0),
            discount_type=promo.get("discount_type") or "percent",
            discount_value=int(promo.get("discount_value") or promo["discount_percent"] or 0),
        )
        payout.update(
            {
                "ok": True,
                "has_partner": True,
                "partner_id": int(promo["partner_id"]),
                "partner_name": promo.get("partner_name") or "Hamkor",
                "promo_code": promo["code"],
                "source": "promo_code",
                "plan_code": plan_code,
            }
        )
        return payout

    if tenant_attr:
        payout = calculate_partner_payout(plan_code, 0)
        payout.update(
            {
                "ok": True,
                "has_partner": True,
                "partner_id": int(tenant_attr["partner_id"]),
                "partner_name": tenant_attr.get("partner_name") or "Hamkor",
                "promo_code": "",
                "source": tenant_attr.get("source") or "referral_link",
                "plan_code": plan_code,
            }
        )
        return payout

    plan = get_plan(plan_code)
    return {
        "ok": True,
        "has_partner": False,
        "discounted_base_amount": int(plan.price),
        "original_amount": int(plan.price),
        "discount_percent": 0,
        "discount_amount": 0,
        "base_commission": 0,
        "commission_amount": 0,
        "promo_code": "",
        "source": "direct",
    }


async def attach_payment_attribution(
    payment_order_id: int,
    tenant_id: int,
    attribution: dict,
    *,
    order_amount: int,
) -> dict | None:
    if not attribution.get("has_partner"):
        return None
    await init_partner_db()
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute(
            """
            INSERT OR IGNORE INTO partner_payment_attributions(
                payment_order_id, tenant_id, partner_id, source, promo_code,
                plan_code, discount_percent, discount_type, discount_value,
                original_amount, discounted_base_amount, order_amount,
                base_commission, discount_amount, commission_amount, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_payment', ?)
            """,
            (
                payment_order_id,
                tenant_id,
                int(attribution["partner_id"]),
                attribution.get("source") or "referral_link",
                attribution.get("promo_code") or "",
                attribution.get("plan_code") or "",
                int(attribution.get("discount_percent") or 0),
                attribution.get("discount_type") or "percent",
                int(attribution.get("discount_value") or attribution.get("discount_percent") or 0),
                int(attribution.get("original_amount") or 0),
                int(attribution.get("discounted_base_amount") or 0),
                int(order_amount),
                int(attribution.get("base_commission") or 0),
                int(attribution.get("discount_amount") or 0),
                int(attribution.get("commission_amount") or 0),
                now,
            ),
        )
        await db.execute(
            "UPDATE business_leads SET status='payment', updated_at=? "
            "WHERE tenant_id=? AND status NOT IN ('lost', 'customer')",
            (now, tenant_id),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT * FROM partner_payment_attributions WHERE payment_order_id=? LIMIT 1",
            (payment_order_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def finalize_sale_for_order(payment_order_id: int, *, actual_amount: int | None = None) -> dict | None:
    """Payment tasdiqlangandan keyin partner komissiyasini bir marta yozadi."""
    await init_partner_db()
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cur = await db.execute(
                "SELECT status FROM payment_orders WHERE id=? LIMIT 1",
                (payment_order_id,),
            )
        except aiosqlite.OperationalError as exc:
            # A standalone partner-db migration/test can run before the core
            # DB exists. It cannot finalize a sale, but must not crash startup.
            if "no such table" in str(exc).lower():
                await db.rollback()
                return None
            raise
        payment = await cur.fetchone()
        if not payment or payment[0] != "approved":
            await db.rollback()
            return None
        cur = await db.execute(
            "SELECT * FROM partner_payment_attributions WHERE payment_order_id=? LIMIT 1",
            (payment_order_id,),
        )
        row = await cur.fetchone()
        if not row:
            await db.commit()
            return None
        attribution = dict(row)
        if attribution["status"] == "approved":
            await db.commit()
            return attribution
        await db.execute(
            """
            UPDATE partner_payment_attributions
            SET status='approved', finalized_at=?, order_amount=COALESCE(?, order_amount)
            WHERE id=?
            """,
            (now, actual_amount, attribution["id"]),
        )
        metadata = json.dumps(
            {
                "payment_order_id": payment_order_id,
                "source": attribution.get("source"),
                "promo_code": attribution.get("promo_code") or "",
                "discount_percent": attribution.get("discount_percent") or 0,
                "discount_amount": attribution.get("discount_amount") or 0,
                "original_amount": attribution.get("original_amount") or 0,
                "discounted_base_amount": attribution.get("discounted_base_amount") or 0,
            },
            ensure_ascii=False,
        )
        await db.execute(
            """
            INSERT INTO partner_referral_events(
                partner_id, event_type, tenant_id, plan_code, amount,
                commission_amount, metadata, created_at
            ) VALUES (?, 'sale', ?, ?, ?, ?, ?, ?)
            """,
            (
                attribution["partner_id"],
                attribution["tenant_id"],
                attribution.get("plan_code") or None,
                actual_amount or attribution["order_amount"],
                attribution["commission_amount"],
                metadata,
                now,
            ),
        )
        await db.execute(
            "UPDATE business_leads SET status='customer', updated_at=? "
            "WHERE tenant_id=? AND status NOT IN ('lost', 'customer')",
            (now, attribution["tenant_id"]),
        )
        await db.commit()
        attribution["status"] = "approved"
        attribution["finalized_at"] = now
        if actual_amount is not None:
            attribution["order_amount"] = actual_amount
        return attribution


async def reconcile_approved_partner_sales(limit: int = 100) -> dict:
    """Repair approved payments whose partner sale was not finalized.

    Finalization is idempotent and protected by an immediate SQLite transaction,
    so this recovery path is safe after transient errors or a process restart.
    """
    await init_partner_db()
    limit = max(1, min(int(limit or 100), 500))
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT p.id, p.amount FROM payment_orders p "
            "JOIN partner_payment_attributions a ON a.payment_order_id=p.id "
            "WHERE p.status='approved' AND a.status!='approved' "
            "ORDER BY p.id LIMIT ?",
            (limit,),
        )
        orders = [dict(row) for row in await cur.fetchall()]
    finalized = 0
    failed = 0
    for order in orders:
        try:
            if await finalize_sale_for_order(order["id"], actual_amount=order["amount"]):
                finalized += 1
        except Exception:
            failed += 1
            logger.exception("Partner sale reconcile failed: order=%s", order["id"])
    return {"found": len(orders), "finalized": finalized, "failed": failed}


async def get_partner_leads(partner_id: int, limit: int = 50) -> list[dict]:
    """Return only business leads attributed to this partner."""
    await init_partner_db()
    limit = max(1, min(int(limit or 50), 100))
    labels = {
        "new": "🆕 Yangi",
        "contacted": "💬 Bog'lanildi",
        "demo": "🎯 Qiziqdi",
        "payment": "💳 To'lov bosqichi",
        "bot_created": "🤖 Bot yaratildi",
        "customer": "✅ Mijoz bo'ldi",
        "lost": "❌ Rad etdi",
    }
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT bl.company_name, bl.contact_name, bl.status, bl.tenant_id, "
            "bl.created_at, bl.updated_at, "
            "COALESCE(bl.partner_id, pta.partner_id) AS attributed_partner_id "
            "FROM business_leads bl "
            "LEFT JOIN partner_tenant_attributions pta ON pta.tenant_id=bl.tenant_id "
            "WHERE bl.partner_id=? OR pta.partner_id=? "
            "ORDER BY bl.updated_at DESC, bl.id DESC LIMIT ?",
            (partner_id, partner_id, limit),
        )
        rows = await cur.fetchall()
    return [
        {
            "company_name": row["company_name"] or "Noma'lum kompaniya",
            "contact_name": row["contact_name"] or "",
            "status": row["status"] or "new",
            "status_label": labels.get(row["status"], row["status"] or "Yangi"),
            "tenant_id": row["tenant_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


async def get_partner_stats(partner_id: int) -> dict:
    await init_partner_db()
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
        cur = await db.execute(
            """
            SELECT
                SUM(CASE WHEN promo_code IS NOT NULL AND promo_code!='' THEN 1 ELSE 0 END) AS promo_orders,
                SUM(CASE WHEN promo_code IS NOT NULL AND promo_code!='' AND status='approved' THEN 1 ELSE 0 END) AS promo_sales
            FROM partner_payment_attributions
            WHERE partner_id=?
            """,
            (partner_id,),
        )
        promo = await cur.fetchone()
        return {
            "clicks": int(row["clicks"] or 0),
            "trials": int(row["trials"] or 0),
            "sales": int(row["sales"] or 0),
            "earned": int(row["earned"] or 0),
            "promo_orders": int(promo["promo_orders"] or 0),
            "promo_sales": int(promo["promo_sales"] or 0),
        }


async def get_partner_activity(partner_id: int, limit: int = 20) -> list[dict]:
    """Return the partner's recent events without exposing private IDs."""
    await init_partner_db()
    limit = max(1, min(int(limit or 20), 50))
    labels = {"click": "Yangi referral", "trial": "Sinov boshlandi", "sale": "Sotuv tasdiqlandi"}
    icons = {"click": "🆕", "trial": "💬", "sale": "✅"}
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT event_type, plan_code, amount, commission_amount, created_at "
            "FROM partner_referral_events WHERE partner_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT ?", (partner_id, limit)
        )
        rows = await cur.fetchall()
    return [{
        "type": row["event_type"], "label": labels.get(row["event_type"], "Faoliyat"),
        "icon": icons.get(row["event_type"], "•"), "plan_code": row["plan_code"] or "",
        "amount": int(row["amount"] or 0), "commission": int(row["commission_amount"] or 0),
        "created_at": row["created_at"],
    } for row in rows]
