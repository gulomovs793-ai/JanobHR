"""Janob HR partner/referral tizimi uchun alohida SQLite qatlami.

Bu modul mavjud Janob HR bazasidan foydalanadi, lekin partner jadvallarini
mustaqil boshqaradi. Shu sabab asosiy tenant/application sxemasiga tegmaydi.
"""

import json
import re
import secrets
from datetime import datetime, timezone

import aiosqlite

from config import SQLITE_PATH
from services.plans import get_plan


PARTNER_COMMISSIONS = {
    "start": 99_000,
    "growth": 199_000,
    "business": 299_000,
}
ALLOWED_PROMO_DISCOUNTS = (0, 5, 10, 15, 20)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def format_uzs(amount: int) -> str:
    return f"{int(amount):,}".replace(",", " ") + " UZS"


def _clean_promo_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())[:32]


def calculate_partner_payout(plan_code: str, discount_percent: int = 0) -> dict:
    plan = get_plan(plan_code)
    discount_percent = int(discount_percent or 0)
    if discount_percent not in ALLOWED_PROMO_DISCOUNTS:
        raise ValueError("Promo chegirma noto'g'ri")
    base_commission = PARTNER_COMMISSIONS.get(plan.code, 0)
    discount_amount = round(plan.price * discount_percent / 100)
    discounted_base_amount = max(0, plan.price - discount_amount)
    commission_amount = max(0, base_commission - discount_amount)
    return {
        "plan_code": plan.code,
        "plan_name": plan.name,
        "original_amount": int(plan.price),
        "discount_percent": discount_percent,
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
                discount_percent INTEGER NOT NULL DEFAULT 0,
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


async def create_or_update_promo_code(partner_id: int, discount_percent: int) -> dict | None:
    """Partner uchun bitta faol promo kod yaratadi. Kod partner referral_code asosida bo'ladi."""
    await init_partner_db()
    discount_percent = int(discount_percent)
    if discount_percent not in ALLOWED_PROMO_DISCOUNTS:
        raise ValueError("Promo foizi noto'g'ri")
    now = _now()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=5000")
        cur = await db.execute(
            "SELECT * FROM partners WHERE id=? AND status='approved' LIMIT 1", (partner_id,)
        )
        partner = await cur.fetchone()
        if not partner or not partner["referral_code"]:
            return None
        code = _clean_promo_code(f"{partner['referral_code']}{discount_percent}")
        await db.execute(
            "UPDATE partner_promo_codes SET status='inactive', updated_at=? WHERE partner_id=? AND status='active'",
            (now, partner_id),
        )
        await db.execute(
            """
            INSERT INTO partner_promo_codes(partner_id, code, discount_percent, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                discount_percent=excluded.discount_percent,
                status='active',
                updated_at=excluded.updated_at
            """,
            (partner_id, code, discount_percent, now, now),
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
            LIMIT 1
            """,
            (cleaned,),
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
        if tenant_attr and int(tenant_attr["partner_id"]) != int(promo["partner_id"]):
            return {
                "ok": False,
                "error": "Bu hisob allaqachon boshqa hamkor orqali kelgan. Boshqa promo kod ishlamaydi.",
            }
        payout = calculate_partner_payout(plan_code, int(promo["discount_percent"]))
        payout.update(
            {
                "ok": True,
                "has_partner": True,
                "partner_id": int(promo["partner_id"]),
                "partner_name": promo.get("partner_name") or "Hamkor",
                "promo_code": promo["code"],
                "source": "promo_code",
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
                discount_percent, original_amount, discounted_base_amount, order_amount,
                base_commission, discount_amount, commission_amount, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_payment', ?)
            """,
            (
                payment_order_id,
                tenant_id,
                int(attribution["partner_id"]),
                attribution.get("source") or "referral_link",
                attribution.get("promo_code") or "",
                int(attribution.get("discount_percent") or 0),
                int(attribution.get("original_amount") or 0),
                int(attribution.get("discounted_base_amount") or 0),
                int(order_amount),
                int(attribution.get("base_commission") or 0),
                int(attribution.get("discount_amount") or 0),
                int(attribution.get("commission_amount") or 0),
                now,
            ),
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
        await db.commit()
        attribution["status"] = "approved"
        attribution["finalized_at"] = now
        if actual_amount is not None:
            attribution["order_amount"] = actual_amount
        return attribution


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
