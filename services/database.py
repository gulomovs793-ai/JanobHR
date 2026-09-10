"""
Janob HR Bot — ma'lumotlar bazasi qatlami (SQLite, aiosqlite), KO'P MIJOZLI (multi-tenant).

MUHIM XAVFSIZLIK QOIDASI: applications, vacancies, interview_slots va
interview_settings jadvallariga tegishli DEYARLI HAR BIR funksiya `tenant_id`ni
BIRINCHI parametr sifatida qabul qiladi va SQL so'rovida albatta ishlatadi —
shu orqali bitta mijoz boshqasining ma'lumotini HECH QACHON ko'ra olmasligi
ta'minlanadi. Yangi funksiya qo'shganda ham shu qoidaga rioya qilish SHART.
"""

import json
import logging
import re
from datetime import datetime, timedelta, timezone

import aiosqlite

from config import SQLITE_PATH

logger = logging.getLogger("janob_hr_bot")


def _json_value(raw, default):
    """Return decoded JSON without letting one corrupt legacy row crash a bot."""
    if raw in (None, ""):
        return default
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return default
    return value


def _json_dict(raw) -> dict:
    value = _json_value(raw, {})
    return value if isinstance(value, dict) else {}


def _json_list(raw) -> list:
    value = _json_value(raw, [])
    return value if isinstance(value, list) else []


def _as_utc_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )


def _normalise_slot_start(value: str | None) -> str | None:
    """Normalize a stored interview time, rejecting malformed legacy input."""
    if value in (None, ""):
        return None
    parsed = _as_utc_datetime(value)
    if parsed is None:
        raise ValueError("Suhbat vaqti noto'g'ri formatda")
    return parsed.isoformat()


def _tenant_from_row(row) -> dict:
    tenant = dict(row)
    tenant["admin_user_ids"] = [
        int(value)
        for value in _json_list(tenant.get("admin_user_ids"))
        if str(value).strip().lstrip("-").isdigit()
    ]
    tenant["onboarding_profile"] = _json_dict(tenant.get("onboarding_profile"))
    return tenant


class ApplicationLimitReached(RuntimeError):
    """Tarif ariza limiti atomik saqlash paytida tugagan."""


class VacancyLimitReached(RuntimeError):
    """Faol vakansiyalar limiti DB transaction ichida tugagan."""


class InterviewSlotConflict(RuntimeError):
    """Bir tenant ichida bir xil faol suhbat vaqti qayta yaratildi."""


class InterviewSlotBooked(RuntimeError):
    """Band qilingan suhbat vaqtini o'chirishga urinish."""


_CREATE_TENANTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    bot_token TEXT NOT NULL UNIQUE,
    bot_username TEXT,
    admin_bot_token TEXT UNIQUE,
    admin_bot_username TEXT,
    admin_user_ids TEXT NOT NULL DEFAULT '[]',
    contact_name TEXT,
    contact_phone TEXT,
    contact_username TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    plan_code TEXT NOT NULL DEFAULT 'trial',
    subscription_started_at TEXT,
    subscription_expires_at TEXT,
    industry TEXT,
    onboarding_profile TEXT NOT NULL DEFAULT '{}',
    onboarding_completed_at TEXT,
    created_at TEXT NOT NULL
);
"""

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    submission_key TEXT,
    username TEXT,
    full_name TEXT,
    vacancy_key TEXT NOT NULL,
    vacancy_title TEXT NOT NULL,
    answers TEXT NOT NULL,
    ai_scores TEXT NOT NULL,
    resume_file_id TEXT,
    video_file_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    admin_messages TEXT NOT NULL DEFAULT '[]',
    selected_slot TEXT,
    phone_number TEXT,
    lang TEXT NOT NULL DEFAULT 'uz',
    ai_suspect_flags TEXT NOT NULL DEFAULT '[]',
    voice_answers TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
"""

_CREATE_VACANCIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS vacancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    title TEXT NOT NULL,
    title_ru TEXT,
    reject_message TEXT NOT NULL,
    reject_message_ru TEXT,
    questions TEXT NOT NULL,
    questions_ru TEXT,
    resume_required INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(tenant_id, key)
);
"""

_CREATE_INTERVIEW_SLOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS interview_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 1,
    starts_at TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

# Suhbat manzili, intervyuchi kontakti va eslatma matni — MIJOZ BOSHIGA bitta
# qator (tenant_id = PRIMARY KEY).
_CREATE_INTERVIEW_SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS interview_settings (
    tenant_id INTEGER PRIMARY KEY,
    location_text TEXT,
    location_lat REAL,
    location_lng REAL,
    interviewer_name TEXT,
    interviewer_phone TEXT,
    notes TEXT
);
"""

# To'lov buyurtmalari — har biriga noyob summa beriladi (asosiy narx +
# tasodifiy 1-200 so'm), shu orqali bank bildirishnomasi qaysi mijozga
# tegishli ekani aniqlanadi.
_CREATE_PAYMENT_ORDERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payment_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    order_code TEXT NOT NULL UNIQUE,
    base_amount INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    plan_code TEXT NOT NULL DEFAULT 'start',
    billing_months INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'awaiting_payment',
    notification_text TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT,
    customer_notified_at TEXT,
    subscription_activated_at TEXT
);
"""

# Bank bildirishnomalarini takror qayta ishlamaslik uchun (30 daqiqalik deduplikatsiya).
_CREATE_PAYMENT_NOTIFICATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payment_notifications_seen (
    hash TEXT PRIMARY KEY,
    amount INTEGER,
    received_at TEXT NOT NULL
);
"""

# Mijoz cheki har bir admin uchun alohida yuboriladi. ``payment_orders`` dagi
# umumiy marker faqat barcha adminlar chekni olgandan keyin qo'yiladi.
_CREATE_CUSTOMER_RECEIPTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payment_customer_receipts (
    order_id INTEGER NOT NULL,
    admin_user_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    claimed_at TEXT,
    sent_at TEXT,
    PRIMARY KEY (order_id, admin_user_id),
    FOREIGN KEY(order_id) REFERENCES payment_orders(id)
);
"""

_CREATE_BUSINESS_LEADS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS business_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    contact_name TEXT,
    contact_phone TEXT NOT NULL,
    contact_username TEXT,
    company_name TEXT,
    hiring_problem TEXT,
    current_process TEXT,
    desired_result TEXT,
    tenant_id INTEGER,
    status TEXT NOT NULL DEFAULT 'new',
    partner_id INTEGER,
    partner_referral_code TEXT,
    partner_promo_code TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_reminded_at TEXT,
    UNIQUE(telegram_user_id, contact_phone)
);
"""

_CREATE_SYSTEM_NOTIFICATIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS system_notifications (
    notification_key TEXT PRIMARY KEY,
    sent_at TEXT NOT NULL
);
"""

# Yangi mijoz qo'shilganda, unga boshlang'ich nuqta sifatida urug'lanadigan
# 3 ta namunaviy vakansiya (avvalgi bir-mijozli tizimdan meros).
_DEFAULT_VACANCIES = [
    {
        "key": "sales",
        "title": "🧑‍💼 Sotuv menejeri",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha ushbu tajriba talablarimizga to'liq mos "
            "kelmayapti, shu sababli ushbu bosqichda davom eta olmaymiz. "
            "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
        ),
        "resume_required": False,
        "questions": [
            {
                "key": "experience",
                "text": "Oldin sotuv sohasida ishlaganmisiz? (Ha/Yo'q)",
                "hard_filter": True,
            },
            {
                "key": "experience_details",
                "text": "Qayerda va qancha muddat sotuv qilgansiz? Qisqacha yozing.",
            },
            {
                "key": "crm",
                "text": "Qanday CRM tizimlarida ishlagansiz? (Bitrix24, amoCRM va h.k.)",
            },
            {
                "key": "scorecard_plan",
                "text": (
                    "Bizning kompaniya keyingi chorakda sotuvni kamida $20,000 ga oshirishi kerak. "
                    "Ishga kelganingizdan keyin birinchi 30 kun ichida bunga qanday hissa qo'shasiz? "
                    "Aniq rejangizni 3 ta qadamda yozing."
                ),
                "ai_score": True,
            },
            {
                "key": "achievement",
                "text": (
                    "Oldingi ish joyingizda erishgan eng katta va aniq yutug'ingizni yozing "
                    "(iloji bo'lsa, raqamlar bilan)."
                ),
                "ai_score": True,
            },
            {
                "key": "mistake_lesson",
                "text": (
                    "Ishingizda yo'l qo'ygan eng jiddiy xatoyingiz nima bo'lgan va undan qanday dars oldingiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "hard_client",
                "text": "Qiyin mijoz bilan qanday ishlaysiz? Bitta real holatni yozib bering.",
                "ai_score": True,
            },
            {
                "key": "teamwork",
                "text": "Jamoada ishlash tajribangizni bitta real misol bilan tushuntiring.",
                "ai_score": True,
            },
            {
                "key": "motivation",
                "text": "Nega aynan bizning kompaniyada ishlashni xohlaysiz?",
                "ai_score": True,
            },
            {
                "key": "salary_expectation",
                "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
            },
        ],
    },
    {
        "key": "designer",
        "title": "🎨 Dizayner",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
            "Portfolioingizni boyitib, keyinroq qayta murojaat qilishingiz mumkin. Omad! 🙏"
        ),
        "resume_required": True,
        "questions": [
            {
                "key": "tool",
                "text": "Figma yoki Adobe (Photoshop/Illustrator) dasturlaridan qaysi birida ishlaysiz?",
            },
            {
                "key": "portfolio",
                "text": "Portfolio (ishlaringiz namunasi) linkini yuboring.",
                "hard_filter": True,
            },
            {
                "key": "scorecard_output",
                "text": (
                    "Bizning brend uchun ijtimoiy tarmoqlarda oyiga kamida 20 ta post dizayni "
                    "tayyorlashingiz kerak bo'ladi. Birinchi haftada ishni qanday tashkil qilasiz "
                    "va sifatni qanday ta'minlaysiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "achievement",
                "text": (
                    "Eng faxrlanadigan loyihangizni tasvirlab bering — u qanday aniq natija "
                    "(masalan, mijoz sotuvi, engagement o'sishi) keltirdi?"
                ),
                "ai_score": True,
            },
            {
                "key": "mistake_lesson",
                "text": "Dizaynda yo'l qo'ygan eng jiddiy xatoyingiz nima bo'lgan va undan qanday dars oldingiz?",
                "ai_score": True,
            },
            {
                "key": "style",
                "text": "Sizga qaysi dizayn yo'nalishi (uslub) yaqinroq va nega?",
                "ai_score": True,
            },
            {
                "key": "deadline_handling",
                "text": "Bir vaqtning o'zida bir nechta muhim topshiriq kelib qolsa, ularni qanday tartibga solasiz?",
                "ai_score": True,
            },
            {
                "key": "feedback_handling",
                "text": "Mijoz yoki rahbar ishingizni qattiq tanqid qilsa, munosabatingiz qanday bo'ladi?",
                "ai_score": True,
            },
            {
                "key": "salary_expectation",
                "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
            },
        ],
    },
    {
        "key": "smm",
        "title": "📱 SMM mutaxassis",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
            "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
        ),
        "resume_required": False,
        "questions": [
            {
                "key": "platforms",
                "text": "Qaysi platformalarda (Instagram, Telegram, TikTok) tajribangiz bor?",
            },
            {
                "key": "content_plan",
                "text": "Kontent-reja tuzish tajribangiz bormi? (Ha/Yo'q)",
                "hard_filter": True,
            },
            {
                "key": "scorecard_growth",
                "text": (
                    "Bizning Instagram sahifamizni 3 oy ichida kamida 5,000 ta yangi obunachiga "
                    "olib chiqishingiz kerak. Buni qanday aniq qadamlar bilan amalga oshirasiz?"
                ),
                "ai_score": True,
            },
            {
                "key": "cases",
                "text": (
                    "Oldingi ishlaringizdan eng yaxshi natija bergan case'ni raqamlar bilan yozib "
                    'bering (masalan: "Reels 100,000 ko\'rishga yetdi").'
                ),
                "ai_score": True,
            },
            {
                "key": "mistake_lesson",
                "text": "SMMda qilgan eng katta xatoyingiz nima edi va undan qanday xulosa chiqardingiz?",
                "ai_score": True,
            },
            {
                "key": "trend_reaction",
                "text": (
                    "Ijtimoiy tarmoqlarda tez o'zgaruvchi trendlarga qanday moslashasiz? "
                    "Oxirgi kuzatgan va ishlatgan trendingizni ayting."
                ),
                "ai_score": True,
            },
            {
                "key": "crisis_management",
                "text": (
                    "Agar brend haqida salbiy komment yoki kichik inqiroziy vaziyat yuzaga kelsa, "
                    "birinchi qadamingiz nima bo'ladi?"
                ),
                "ai_score": True,
            },
            {
                "key": "tools",
                "text": "Qanday dizayn/analitika vositalaridan (Canva, Meta Business Suite va h.k.) foydalanasiz?",
            },
            {
                "key": "salary_expectation",
                "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)",
            },
        ],
    },
]


async def init_db():
    """Faqat jadval strukturasini yaratadi. Mijozga xos ma'lumot (vakansiyalar
    va h.k.) endi `create_tenant()` orqali, yangi mijoz qo'shilganda urug'lanadi —
    bu yerda GLOBAL seed yo'q (ko'p mijozli tizimda ma'nosiz bo'lardi)."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(_CREATE_TENANTS_TABLE_SQL)
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_CREATE_VACANCIES_TABLE_SQL)
        await db.execute(_CREATE_INTERVIEW_SLOTS_TABLE_SQL)
        await db.execute(_CREATE_INTERVIEW_SETTINGS_TABLE_SQL)
        await db.execute(_CREATE_PAYMENT_ORDERS_TABLE_SQL)
        await db.execute(_CREATE_PAYMENT_NOTIFICATIONS_TABLE_SQL)
        await db.execute(_CREATE_CUSTOMER_RECEIPTS_TABLE_SQL)
        await db.execute(_CREATE_BUSINESS_LEADS_TABLE_SQL)
        await db.execute(_CREATE_SYSTEM_NOTIFICATIONS_TABLE_SQL)

        # Ko'p async handler bir vaqtda o'qib/yozishi mumkin. WAL readerlarni
        # writer sabab bloklanishini kamaytiradi; busy_timeout qisqa locklarda
        # tasodifiy "database is locked" xatosini oldini oladi.
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA busy_timeout=5000")

        cursor = await db.execute("PRAGMA table_info(applications)")
        application_columns = {row[1] for row in await cursor.fetchall()}
        if "submission_key" not in application_columns:
            await db.execute("ALTER TABLE applications ADD COLUMN submission_key TEXT")
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_applications_submission_key "
            "ON applications(tenant_id, submission_key) "
            "WHERE submission_key IS NOT NULL"
        )

        # Mavjud Render diskidagi eski bazalarni ma'lumot yo'qotmasdan
        # yangilaymiz. SQLite `ADD COLUMN` uchun IF NOT EXISTS bermaydi.
        cursor = await db.execute("PRAGMA table_info(tenants)")
        tenant_columns = {row[1] for row in await cursor.fetchall()}
        for column in ("contact_name", "contact_phone", "contact_username"):
            if column not in tenant_columns:
                await db.execute(f"ALTER TABLE tenants ADD COLUMN {column} TEXT")
        tenant_migrations = {
            "plan_code": "TEXT NOT NULL DEFAULT 'trial'",
            "subscription_started_at": "TEXT",
            "subscription_expires_at": "TEXT",
            "industry": "TEXT",
            "onboarding_profile": "TEXT NOT NULL DEFAULT '{}'",
            "onboarding_completed_at": "TEXT",
        }
        plan_was_missing = "plan_code" not in tenant_columns
        for column, definition in tenant_migrations.items():
            if column not in tenant_columns:
                await db.execute(
                    f"ALTER TABLE tenants ADD COLUMN {column} {definition}"
                )
        if plan_was_missing:
            await db.execute(
                "UPDATE tenants SET plan_code = 'legacy' WHERE status = 'active'"
            )
        cursor = await db.execute("PRAGMA table_info(vacancies)")
        vacancy_columns = {row[1] for row in await cursor.fetchall()}
        if "profile_json" not in vacancy_columns:
            await db.execute("ALTER TABLE vacancies ADD COLUMN profile_json TEXT NOT NULL DEFAULT '{}'")

        cursor = await db.execute("PRAGMA table_info(interview_slots)")
        slot_columns = {row[1] for row in await cursor.fetchall()}
        if "starts_at" not in slot_columns:
            await db.execute("ALTER TABLE interview_slots ADD COLUMN starts_at TEXT")

        cursor = await db.execute("PRAGMA table_info(payment_orders)")
        payment_columns = {row[1] for row in await cursor.fetchall()}
        if "plan_code" not in payment_columns:
            await db.execute(
                "ALTER TABLE payment_orders ADD COLUMN plan_code TEXT NOT NULL DEFAULT 'start'"
            )
        if "billing_months" not in payment_columns:
            await db.execute(
                "ALTER TABLE payment_orders ADD COLUMN billing_months INTEGER NOT NULL DEFAULT 1"
            )
        if "customer_notified_at" not in payment_columns:
            await db.execute(
                "ALTER TABLE payment_orders ADD COLUMN customer_notified_at TEXT"
            )
        marker_was_missing = "subscription_activated_at" not in payment_columns
        if marker_was_missing:
            await db.execute(
                "ALTER TABLE payment_orders ADD COLUMN subscription_activated_at TEXT"
            )
            # Historical approved orders were already activated before this
            # marker existed. Mark them as reconciled so a fresh deploy cannot
            # extend every old subscription a second time.
            await db.execute(
                "UPDATE payment_orders SET subscription_activated_at="
                "COALESCE(decided_at, created_at) "
                "WHERE status='approved' AND subscription_activated_at IS NULL"
            )

        # Defense-in-depth for payment routing: even if application-level locking
        # regresses later, SQLite itself must never allow two LIVE orders to own
        # the same exact incoming amount. Historical duplicates from older code
        # are ambiguous, so mark every still-live duplicate for manual review
        # before creating the partial UNIQUE index.
        duplicate_now = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "SELECT amount FROM payment_orders WHERE status='awaiting_payment' "
            "GROUP BY amount HAVING COUNT(*) > 1"
        )
        for (duplicate_amount,) in await cursor.fetchall():
            logger.error(
                "Duplicate live payment amount migrationda topildi: %s; needs_review qilindi.",
                duplicate_amount,
            )
            await db.execute(
                "UPDATE payment_orders SET status='needs_review', "
                "decided_at=COALESCE(decided_at, ?) "
                "WHERE amount=? AND status='awaiting_payment'",
                (duplicate_now, duplicate_amount),
            )
        await db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_orders_awaiting_amount "
            "ON payment_orders(amount) WHERE status='awaiting_payment'"
        )

        cursor = await db.execute("PRAGMA table_info(business_leads)")
        lead_columns = {row[1] for row in await cursor.fetchall()}
        if "last_reminded_at" not in lead_columns:
            await db.execute(
                "ALTER TABLE business_leads ADD COLUMN last_reminded_at TEXT"
            )
        for column, definition in (
            ("partner_id", "INTEGER"),
            ("partner_referral_code", "TEXT"),
            ("partner_promo_code", "TEXT"),
        ):
            if column not in lead_columns:
                await db.execute(
                    f"ALTER TABLE business_leads ADD COLUMN {column} {definition}"
                )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_business_leads_partner "
            "ON business_leads(partner_id, updated_at)"
        )
        cursor = await db.execute(
            "SELECT id, company_name, admin_user_ids, contact_name, contact_phone, "
            "contact_username, created_at FROM tenants "
            "WHERE contact_phone IS NOT NULL AND contact_phone != ''"
        )
        for tenant in await cursor.fetchall():
            try:
                admin_ids = json.loads(tenant[2] or "[]")
                telegram_user_id = int(admin_ids[0]) if admin_ids else -int(tenant[0])
            except (TypeError, ValueError, json.JSONDecodeError):
                telegram_user_id = -int(tenant[0])
            await db.execute(
                "INSERT OR IGNORE INTO business_leads "
                "(telegram_user_id, contact_name, contact_phone, contact_username, "
                "company_name, tenant_id, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'bot_created', ?, ?)",
                (
                    telegram_user_id,
                    tenant[3] or "",
                    tenant[4],
                    tenant[5] or "",
                    tenant[1],
                    tenant[0],
                    tenant[6],
                    tenant[6],
                ),
            )
        await db.commit()
    logger.info("Ma'lumotlar bazasi (ko'p mijozli) tayyor: %s", SQLITE_PATH)


async def healthcheck() -> bool:
    """Render health endpoint uchun eng arzon real DB tekshiruvi."""
    try:
        async with aiosqlite.connect(SQLITE_PATH, timeout=3) as db:
            await db.execute("PRAGMA busy_timeout=3000")
            cursor = await db.execute("SELECT 1")
            row = await cursor.fetchone()
        return bool(row and row[0] == 1)
    except Exception:
        logger.exception("SQLite healthcheck muvaffaqiyatsiz.")
        return False


# ============================= MIJOZLAR (tenants) =============================


def _bot_identity(token: str) -> str:
    token = (token or "").strip()
    prefix, separator, _ = token.partition(":")
    return prefix if separator and prefix.isdigit() else token


def is_reserved_bot_token(token: str) -> bool:
    import config

    identity = _bot_identity(token)
    return bool(identity) and any(
        value and _bot_identity(value) == identity
        for value in (config.BOT_TOKEN, config.ADMIN_BOT_TOKEN,
                      config.FOUNDER_BOT_TOKEN, config.PARTNER_BOT_TOKEN, config.SETUP_BOT_TOKEN)
    )


async def create_tenant(
    company_name: str,
    bot_token: str,
    admin_bot_token: str,
    admin_user_ids: list[int],
    contact_name: str = "",
    contact_phone: str = "",
    contact_username: str = "",
) -> int:
    """Yangi mijozni toza workspace bilan yaratadi.

    Trial 1 ta faol vakansiyaga ruxsat beradi. Avvalgi 3 ta umumiy demo
    vakansiyani avtomatik aktiv yaratish yangi tenantni tug'ilishi bilan limitdan
    oshirib qo'yardi va mijoz o'z vakansiyasini yaratolmasdi. Endi tenant bo'sh
    boshlanadi; birinchi vakansiyani Admin bot yoki Mini App onboarding yaratadi.
    """
    bot_token = (bot_token or "").strip()
    admin_bot_token = (admin_bot_token or "").strip()
    if not bot_token or not admin_bot_token or _bot_identity(bot_token) == _bot_identity(admin_bot_token):
        raise ValueError("Nomzod va admin botlari alohida bo'lishi kerak")
    if is_reserved_bot_token(bot_token) or is_reserved_bot_token(admin_bot_token):
        raise ValueError("Tizim botini mijoz boti sifatida ulab bo'lmaydi")
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=10) as db:
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("BEGIN IMMEDIATE")
        existing = await (await db.execute("SELECT bot_token, admin_bot_token FROM tenants")).fetchall()
        identities = {_bot_identity(token) for row in existing for token in row if token}
        if identities.intersection({_bot_identity(bot_token), _bot_identity(admin_bot_token)}):
            raise ValueError("Bu bot allaqachon ro'yxatdan o'tgan")
        cursor = await db.execute(
            "INSERT INTO tenants (company_name, bot_token, admin_bot_token, admin_user_ids, "
            "contact_name, contact_phone, contact_username, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                company_name,
                bot_token,
                admin_bot_token,
                json.dumps(admin_user_ids),
                contact_name,
                contact_phone,
                contact_username,
                created_at,
            ),
        )
        tenant_id = cursor.lastrowid
        await db.commit()
    logger.info("Yangi mijoz yaratildi: id=%s, %s", tenant_id, company_name)
    return tenant_id


async def get_tenant(tenant_id: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        row = await cursor.fetchone()
    if not row:
        return None
    return _tenant_from_row(row)


async def get_tenant_by_role_token(token: str) -> tuple[dict, str] | None:
    """Berilgan token — nomzod-bot yoki Admin panel-bot tokenlaridan qaysi biriga
    mos kelishini tekshiradi. Topilsa (mijoz, rol) qaytaradi, rol — "candidate"
    yoki "admin". Hech biriga mos kelmasa None qaytaradi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tenants WHERE bot_token = ?", (token,))
        row = await cursor.fetchone()
        if row:
            return _tenant_from_row(row), "candidate"

        cursor = await db.execute(
            "SELECT * FROM tenants WHERE admin_bot_token = ?", (token,)
        )
        row = await cursor.fetchone()
        if row:
            return _tenant_from_row(row), "admin"

    return None


async def get_tenant_by_token(bot_token: str) -> dict | None:
    """ESKIRGAN: `get_tenant_by_role_token`ni ishlating. Faqat orqaga moslik
    uchun (masalan `/create_bot`da "bu token allaqachon band" tekshiruvi
    ikkala ustunni ham qamrab olishi kerak — shu funksiya endi ikkalasini
    ham tekshiradi)."""
    result = await get_tenant_by_role_token(bot_token)
    return result[0] if result else None


async def list_tenants(status: str | None = None) -> list[dict]:
    query = "SELECT * FROM tenants"
    params = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY created_at DESC"
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        result.append(_tenant_from_row(row))
    return result


async def get_founder_stats() -> dict:
    """Founder panel uchun platforma bo'yicha qisqa biznes ko'rsatkichlari."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM tenants GROUP BY status"
        )
        tenant_counts = dict(await cursor.fetchall())
        cursor = await db.execute("SELECT COUNT(*) FROM applications")
        total_applications = (await cursor.fetchone())[0]
        cursor = await db.execute(
            "SELECT COUNT(*) FROM applications WHERE created_at >= ?",
            ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),),
        )
        monthly_applications = (await cursor.fetchone())[0]
        cursor = await db.execute("SELECT COUNT(*) FROM business_leads")
        business_leads = (await cursor.fetchone())[0]
        today = datetime.now(timezone.utc).date().isoformat()
        cursor = await db.execute(
            "SELECT COUNT(*) FROM business_leads WHERE substr(created_at, 1, 10)=?",
            (today,),
        )
        today_leads = (await cursor.fetchone())[0]
        cursor = await db.execute(
            "SELECT COUNT(*) FROM payment_orders WHERE status='awaiting_payment'"
        )
        awaiting_payments = (await cursor.fetchone())[0]
        cursor = await db.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payment_orders "
            "WHERE status='approved' AND decided_at >= ?",
            ((datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),),
        )
        monthly_revenue = (await cursor.fetchone())[0]
        cursor = await db.execute(
            "SELECT COUNT(*) FROM tenants WHERE status='active' "
            "AND subscription_expires_at IS NOT NULL AND subscription_expires_at <= ?",
            ((datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),),
        )
        expiring_soon = (await cursor.fetchone())[0]
    return {
        "pending": tenant_counts.get("pending", 0),
        "active": tenant_counts.get("active", 0),
        "inactive": tenant_counts.get("inactive", 0),
        "total_applications": total_applications,
        "monthly_applications": monthly_applications,
        "business_leads": business_leads,
        "today_leads": today_leads,
        "awaiting_payments": awaiting_payments,
        "monthly_revenue": monthly_revenue,
        "expiring_soon": expiring_soon,
    }


async def get_founder_dashboard_data() -> dict:
    """Founder Mini App uchun platformadagi jonli biznes ma'lumotlari.

    Barcha hisoblar bir xil SQLite snapshotidan olinadi. Bot tokenlari va boshqa
    maxfiy maydonlar javobga umuman kiritilmaydi.
    """
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    day_ago = (now - timedelta(days=1)).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()
    renewal_cutoff = (now + timedelta(days=7)).isoformat()

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row

        cursor = await db.execute(
            "SELECT status, COUNT(*) AS count FROM tenants GROUP BY status"
        )
        tenant_counts = {row["status"]: row["count"] for row in await cursor.fetchall()}

        cursor = await db.execute(
            "SELECT plan_code, COUNT(*) AS count FROM tenants "
            "WHERE status='active' GROUP BY plan_code ORDER BY count DESC"
        )
        plan_counts = [dict(row) for row in await cursor.fetchall()]

        async def scalar(sql: str, params: tuple = ()) -> int:
            item = await (await db.execute(sql, params)).fetchone()
            return int(item[0] or 0)

        revenue = {
            "today": await scalar(
                "SELECT SUM(amount) FROM payment_orders WHERE status='approved' AND decided_at>=?",
                (day_ago,),
            ),
            "week": await scalar(
                "SELECT SUM(amount) FROM payment_orders WHERE status='approved' AND decided_at>=?",
                (week_ago,),
            ),
            "month": await scalar(
                "SELECT SUM(amount) FROM payment_orders WHERE status='approved' AND decided_at>=?",
                (month_ago,),
            ),
            "all": await scalar(
                "SELECT SUM(amount) FROM payment_orders WHERE status='approved'"
            ),
        }
        payment_statuses = {
            "awaiting_payment": await scalar(
                "SELECT COUNT(*) FROM payment_orders WHERE status='awaiting_payment'"
            ),
            "needs_review": await scalar(
                "SELECT COUNT(*) FROM payment_orders WHERE status='needs_review'"
            ),
            "approved_30d": await scalar(
                "SELECT COUNT(*) FROM payment_orders WHERE status='approved' AND decided_at>=?",
                (month_ago,),
            ),
        }
        applications = {
            "today": await scalar(
                "SELECT COUNT(*) FROM applications WHERE created_at>=?", (day_ago,)
            ),
            "month": await scalar(
                "SELECT COUNT(*) FROM applications WHERE created_at>=?", (month_ago,)
            ),
            "all": await scalar("SELECT COUNT(*) FROM applications"),
        }
        leads = {
            "new": await scalar("SELECT COUNT(*) FROM business_leads WHERE status='new'"),
            "all": await scalar("SELECT COUNT(*) FROM business_leads"),
        }

        cursor = await db.execute(
            "SELECT t.id, t.company_name, t.contact_name, t.contact_phone, "
            "t.contact_username, t.status, t.plan_code, t.subscription_expires_at, "
            "t.created_at, COUNT(DISTINCT a.id) AS applications, "
            "COUNT(DISTINCT CASE WHEN v.active=1 THEN v.id END) AS active_vacancies "
            "FROM tenants t "
            "LEFT JOIN applications a ON a.tenant_id=t.id "
            "LEFT JOIN vacancies v ON v.tenant_id=t.id "
            "GROUP BY t.id ORDER BY t.created_at DESC"
        )
        customers = [dict(row) for row in await cursor.fetchall()]

        cursor = await db.execute(
            "SELECT p.id, p.order_code, p.amount, p.plan_code, p.status, p.created_at, "
            "p.expires_at, p.decided_at, t.id AS tenant_id, t.company_name, t.contact_phone "
            "FROM payment_orders p JOIN tenants t ON t.id=p.tenant_id "
            "ORDER BY p.created_at DESC LIMIT 100"
        )
        payments = [dict(row) for row in await cursor.fetchall()]

    renewal_cutoff_dt = _as_utc_datetime(renewal_cutoff) or now
    renewals = []
    for item in customers:
        expires = _as_utc_datetime(item.get("subscription_expires_at"))
        if item["status"] == "active" and expires and expires <= renewal_cutoff_dt:
            renewals.append(item)
    for item in renewals:
        expires = _as_utc_datetime(item["subscription_expires_at"])
        item["days_left"] = (
            max(-999, (expires.date() - now.date()).days) if expires else -999
        )
    renewals.sort(key=lambda item: item.get("subscription_expires_at") or "")

    return {
        "generated_at": now_iso,
        "tenants": {
            "total": sum(tenant_counts.values()),
            "active": tenant_counts.get("active", 0),
            "pending": tenant_counts.get("pending", 0),
            "inactive": tenant_counts.get("inactive", 0),
        },
        "plans": plan_counts,
        "revenue": revenue,
        "payments": payment_statuses,
        "applications": applications,
        "leads": leads,
        "renewals": renewals,
        "customers": customers,
        "recent_payments": payments,
    }


async def save_business_lead(**lead) -> int:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "INSERT INTO business_leads (telegram_user_id, contact_name, contact_phone, "
            "contact_username, company_name, hiring_problem, current_process, desired_result, "
            "partner_id, partner_referral_code, partner_promo_code, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(telegram_user_id, contact_phone) DO UPDATE SET "
            "contact_name=excluded.contact_name, contact_username=excluded.contact_username, "
            "company_name=excluded.company_name, hiring_problem=excluded.hiring_problem, "
            "current_process=excluded.current_process, desired_result=excluded.desired_result, "
            "partner_id=COALESCE(business_leads.partner_id, excluded.partner_id), "
            "partner_referral_code=CASE WHEN business_leads.partner_id IS NULL THEN excluded.partner_referral_code "
            "ELSE business_leads.partner_referral_code END, "
            "partner_promo_code=CASE WHEN business_leads.partner_id IS NULL THEN excluded.partner_promo_code "
            "ELSE business_leads.partner_promo_code END, "
            "updated_at=excluded.updated_at",
            (
                lead["telegram_user_id"],
                lead.get("contact_name", ""),
                lead["contact_phone"],
                lead.get("contact_username", ""),
                lead.get("company_name", ""),
                lead.get("hiring_problem", ""),
                lead.get("current_process", ""),
                lead.get("desired_result", ""),
                lead.get("partner_id"),
                lead.get("partner_referral_code"),
                lead.get("partner_promo_code"),
                now,
                now,
            ),
        )
        cursor = await db.execute(
            "SELECT id FROM business_leads WHERE telegram_user_id=? AND contact_phone=?",
            (lead["telegram_user_id"], lead["contact_phone"]),
        )
        row = await cursor.fetchone()
        await db.commit()
    return row[0]


async def attach_business_lead_to_tenant(lead_id: int, tenant_id: int) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE business_leads SET tenant_id=?, status='bot_created', updated_at=? WHERE id=?",
            (tenant_id, datetime.now(timezone.utc).isoformat(), lead_id),
        )
        await db.commit()


async def list_business_leads() -> list[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM business_leads ORDER BY updated_at DESC"
        )
        return [dict(row) for row in await cursor.fetchall()]


async def get_business_lead(lead_id: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM business_leads WHERE id=?", (lead_id,))
        row = await cursor.fetchone()
    return dict(row) if row else None


LEAD_STATUSES = {
    "new",
    "contacted",
    "demo",
    "payment",
    "customer",
    "lost",
    "bot_created",
}


async def update_business_lead_status(lead_id: int, status: str) -> bool:
    if status not in LEAD_STATUSES:
        return False
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "UPDATE business_leads SET status=?, updated_at=? WHERE id=?",
            (status, datetime.now(timezone.utc).isoformat(), lead_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_payment_order_for_tenant(tenant_id: int, order_code: str) -> dict | None:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # UI polling eski orderni hali ham "kutilmoqda" deb ko'rsatmasin.
        await db.execute(
            "UPDATE payment_orders SET status='expired', "
            "decided_at=COALESCE(decided_at, ?) "
            "WHERE tenant_id=? AND UPPER(order_code)=UPPER(?) "
            "AND status='awaiting_payment' AND expires_at<=?",
            (now_iso, tenant_id, order_code.strip(), now_iso),
        )
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE tenant_id=? AND UPPER(order_code)=UPPER(?) LIMIT 1",
            (tenant_id, order_code.strip()),
        )
        row = await cursor.fetchone()
        await db.commit()
    return dict(row) if row else None


async def list_due_lead_reminders(hours: int = 24) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM business_leads WHERE status IN ('new','contacted','demo','payment') "
            "AND updated_at <= ? AND (last_reminded_at IS NULL OR last_reminded_at <= ?) "
            "ORDER BY updated_at LIMIT 50",
            (cutoff, cutoff),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def list_leads_older_than(minutes: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM business_leads WHERE status IN ('new','contacted') "
            "AND created_at <= ? ORDER BY created_at LIMIT 100",
            (cutoff,),
        )
        return [dict(row) for row in await cursor.fetchall()]


async def list_unpaid_orders_older_than(minutes: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    cutoff = (now - timedelta(minutes=minutes)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        # Reminder sikli payment parser ishlamasa ham TTLni o'zi hurmat qiladi.
        await db.execute(
            "UPDATE payment_orders SET status='expired', "
            "decided_at=COALESCE(decided_at, ?) "
            "WHERE status='awaiting_payment' AND expires_at<=?",
            (now_iso, now_iso),
        )
        cursor = await db.execute(
            "SELECT p.*, t.company_name, t.contact_phone FROM payment_orders p "
            "JOIN tenants t ON t.id=p.tenant_id "
            "WHERE p.status='awaiting_payment' AND p.created_at <= ? AND p.expires_at > ? "
            "ORDER BY p.created_at LIMIT 100",
            (cutoff, now_iso),
        )
        rows = [dict(row) for row in await cursor.fetchall()]
        await db.commit()
        return rows


async def mark_lead_reminded(lead_id: int) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE business_leads SET last_reminded_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), lead_id),
        )
        await db.commit()


async def was_system_notification_sent(key: str) -> bool:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM system_notifications WHERE notification_key=?", (key,)
        )
        return bool(await cursor.fetchone())


async def mark_system_notification_sent(key: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO system_notifications(notification_key, sent_at) VALUES (?, ?)",
            (key, datetime.now(timezone.utc).isoformat()),
        )
        await db.commit()


async def list_expiring_subscriptions(days: int) -> list[dict]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days + 1)
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tenants WHERE status='active' AND plan_code NOT IN ('trial','legacy') "
            "AND subscription_expires_at > ? AND subscription_expires_at <= ?",
            (now.isoformat(), end.isoformat()),
        )
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        result.append(_tenant_from_row(row))
    return result


async def list_subscription_reminder_candidates() -> list[dict]:
    now = datetime.now(timezone.utc)
    lower = now - timedelta(days=7)
    upper = now + timedelta(days=6)
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM tenants WHERE status='active' AND plan_code NOT IN ('trial','legacy') "
            "AND subscription_expires_at >= ? AND subscription_expires_at <= ?",
            (lower.isoformat(), upper.isoformat()),
        )
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        result.append(_tenant_from_row(row))
    return result


async def update_tenant_status(
    tenant_id: int, status: str, bot_username: str | None = None
) -> bool:
    """Update one tenant and report whether the target still existed."""
    if status not in {"pending", "active", "inactive"}:
        raise ValueError("Noto'g'ri mijoz holati")
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            if bot_username is not None:
                cursor = await db.execute(
                    "UPDATE tenants SET status = ?, bot_username = ? WHERE id = ?",
                    (status, bot_username, tenant_id),
                )
            else:
                cursor = await db.execute(
                    "UPDATE tenants SET status = ? WHERE id = ?", (status, tenant_id)
                )
            await db.commit()
            return cursor.rowcount == 1
        except Exception:
            await db.rollback()
            raise


async def set_admin_bot_username(tenant_id: int, username: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE tenants SET admin_bot_username = ? WHERE id = ?",
            (username, tenant_id),
        )
        await db.commit()


async def get_subscription_usage(tenant_id: int) -> dict:
    """Tarif va joriy hisob davridagi real foydalanish."""
    from services.plans import get_plan

    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise ValueError("Mijoz topilmadi")
    plan = get_plan(tenant.get("plan_code"))
    period_start = tenant.get("subscription_started_at") or tenant["created_at"]
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM applications WHERE tenant_id = ? AND created_at >= ?",
            (tenant_id, period_start),
        )
        applications_used = (await cursor.fetchone())[0]
        cursor = await db.execute(
            "SELECT COUNT(*) FROM vacancies WHERE tenant_id = ? AND active = 1",
            (tenant_id,),
        )
        vacancies_used = (await cursor.fetchone())[0]
    expires_at = tenant.get("subscription_expires_at")
    expires_dt = _as_utc_datetime(expires_at)
    expired = bool(
        plan.code not in {"trial", "legacy"}
        and (not expires_dt or expires_dt <= datetime.now(timezone.utc))
    )
    return {
        "plan": plan,
        "applications_used": applications_used,
        "vacancies_used": vacancies_used,
        "expired": expired,
        "applications_available": not expired
        and (
            plan.application_limit is None or applications_used < plan.application_limit
        ),
        "vacancies_available": not expired
        and (plan.vacancy_limit is None or vacancies_used < plan.vacancy_limit),
        "expires_at": expires_at,
    }


async def activate_subscription(
    tenant_id: int, plan_code: str, months: int = 1
) -> None:
    from services.plans import PUBLIC_PLAN_CODES, get_plan_transition

    if plan_code not in PUBLIC_PLAN_CODES:
        raise ValueError("Noto'g'ri tarif")
    months = int(months)
    if not 1 <= months <= 12:
        raise ValueError("Billing oylar soni 1–12 oralig'ida bo'lishi kerak")
    tenant = await get_tenant(tenant_id)
    if not tenant:
        raise ValueError("Mijoz topilmadi")
    usage = await get_subscription_usage(tenant_id)
    if get_plan_transition(
        usage["plan"].code,
        plan_code,
        current_expired=usage["expired"],
    ) == "blocked":
        raise ValueError(
            "Faol tarif muddati tugamaguncha past tarifga o'tib bo'lmaydi"
        )
    now = datetime.now(timezone.utc)
    current_expiry = _as_utc_datetime(tenant.get("subscription_expires_at")) or now
    expires = max(now, current_expiry) + timedelta(days=30 * max(1, months))
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "UPDATE tenants SET plan_code = ?, subscription_started_at = ?, "
                "subscription_expires_at = ? WHERE id = ?",
                (plan_code, now.isoformat(), expires.isoformat(), tenant_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Mijoz topilmadi")
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def activate_subscription_for_order(order_id: int) -> dict:
    """Activate one approved payment exactly once.

    Payment approval and tenant subscription activation are separate concerns,
    so this marker makes automatic recovery and Founder manual retry safe. A
    process restart after activation cannot extend the same order again.
    """
    from services.plans import PUBLIC_PLAN_CODES, get_plan, get_plan_transition

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=10) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT p.*, t.plan_code AS current_plan, "
                "t.subscription_started_at AS current_started_at, "
                "t.subscription_expires_at AS current_expires_at "
                "FROM payment_orders p JOIN tenants t ON t.id=p.tenant_id "
                "WHERE p.id=? LIMIT 1",
                (order_id,),
            )
            order = await cursor.fetchone()
            if not order:
                raise ValueError("To'lov buyurtmasi topilmadi")
            if order["subscription_activated_at"]:
                await db.commit()
                return {"ok": True, "already_activated": True, "order": dict(order)}
            if order["status"] != "approved":
                raise ValueError("Faqat tasdiqlangan to'lov tarifni yoqa oladi")

            plan_code = str(order["plan_code"] or "").lower()
            months = int(order["billing_months"] or 0)
            if plan_code not in PUBLIC_PLAN_CODES or not 1 <= months <= 12:
                raise ValueError("To'lov buyurtmasining tarifi yoki muddati noto'g'ri")
            current_plan = get_plan(order["current_plan"])
            current_expiry = _as_utc_datetime(order["current_expires_at"])
            expired = current_plan.code not in {"trial", "legacy"} and (
                not current_expiry or current_expiry <= now
            )
            if get_plan_transition(
                current_plan.code, plan_code, current_expired=expired
            ) == "blocked":
                raise ValueError("Faol yuqori tarif sabab past tarif yoqilmadi")
            expires = max(now, current_expiry or now) + timedelta(days=30 * months)
            tenant_update = await db.execute(
                "UPDATE tenants SET plan_code=?, subscription_started_at=?, "
                "subscription_expires_at=? WHERE id=?",
                (plan_code, now_iso, expires.isoformat(), order["tenant_id"]),
            )
            if tenant_update.rowcount != 1:
                raise ValueError("Mijoz topilmadi")
            await db.execute(
                "UPDATE business_leads SET status='customer', updated_at=? WHERE tenant_id=?",
                (now_iso, order["tenant_id"]),
            )
            marker_update = await db.execute(
                "UPDATE payment_orders SET subscription_activated_at=? WHERE id=? "
                "AND subscription_activated_at IS NULL",
                (now_iso, order_id),
            )
            if marker_update.rowcount != 1:
                raise RuntimeError("To'lov aktivatsiyasi parallel o'zgardi")
            await db.commit()
            return {
                "ok": True,
                "already_activated": False,
                "order": dict(order),
                "expires_at": expires.isoformat(),
            }
        except Exception:
            await db.rollback()
            raise


# ============================= ARIZALAR (applications) =============================


def _parse_app_row(row) -> dict:
    app = dict(row)
    app["answers"] = _json_dict(app.get("answers"))
    app["ai_scores"] = _json_dict(app.get("ai_scores"))
    app["admin_messages"] = _json_list(app.get("admin_messages"))
    app["ai_suspect_flags"] = _json_list(app.get("ai_suspect_flags"))
    app["voice_answers"] = _json_dict(app.get("voice_answers"))
    return app


async def save_application(
    *,
    tenant_id: int,
    user_id: int,
    username: str,
    full_name: str,
    vacancy_key: str,
    vacancy_title: str,
    answers: dict,
    ai_scores: dict,
    resume_file_id: str | None,
    video_file_id: str | None,
    status: str,
    phone_number: str = "",
    lang: str = "uz",
    ai_suspect_flags: list | None = None,
    voice_answers: dict | None = None,
    submission_key: str | None = None,
) -> int:
    """Arizani idempotent va tarif limitiga nisbatan atomik saqlaydi.

    Avvalgi get_subscription_usage() -> INSERT ketma-ketligi race condition
    qoldirardi: limitda 1 joy qolsa, ikki nomzod bir paytda o'tib ketishi
    mumkin edi. BEGIN IMMEDIATE bilan quota tekshiruvi va INSERT bitta write
    transaction ichida bajariladi.
    """
    from services.plans import get_plan

    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            if submission_key:
                cursor = await db.execute(
                    "SELECT id FROM applications WHERE tenant_id=? AND submission_key=? LIMIT 1",
                    (tenant_id, submission_key),
                )
                existing = await cursor.fetchone()
                if existing:
                    await db.commit()
                    return existing[0]

            cursor = await db.execute(
                "SELECT plan_code, subscription_started_at, subscription_expires_at, created_at "
                "FROM tenants WHERE id=?",
                (tenant_id,),
            )
            tenant = await cursor.fetchone()
            if not tenant:
                raise ValueError("Mijoz topilmadi")

            plan = get_plan(tenant[0])
            expires_at = tenant[2]
            expired = bool(
                plan.code not in {"trial", "legacy"}
                and (not expires_at or expires_at <= created_at)
            )
            if expired:
                raise ApplicationLimitReached("Tarif muddati tugagan")

            if plan.application_limit is not None:
                period_start = tenant[1] or tenant[3]
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM applications WHERE tenant_id=? AND created_at>=?",
                    (tenant_id, period_start),
                )
                used = (await cursor.fetchone())[0]
                if used >= plan.application_limit:
                    raise ApplicationLimitReached("Tarifdagi ariza limiti tugagan")

            cursor = await db.execute(
                """
                INSERT INTO applications (
                    tenant_id, user_id, submission_key, username, full_name, vacancy_key,
                    vacancy_title, answers, ai_scores, resume_file_id, video_file_id, status,
                    phone_number, lang, ai_suspect_flags, voice_answers, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    user_id,
                    submission_key,
                    username,
                    full_name,
                    vacancy_key,
                    vacancy_title,
                    json.dumps(answers, ensure_ascii=False),
                    json.dumps(ai_scores, ensure_ascii=False),
                    resume_file_id,
                    video_file_id,
                    status,
                    phone_number,
                    lang,
                    json.dumps(ai_suspect_flags or [], ensure_ascii=False),
                    json.dumps(voice_answers or {}, ensure_ascii=False),
                    created_at,
                ),
            )
            await db.commit()
            return cursor.lastrowid
        except Exception:
            await db.rollback()
            raise


async def get_application(tenant_id: int, app_id: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE id = ? AND tenant_id = ?",
            (app_id, tenant_id),
        )
        row = await cursor.fetchone()
    return _parse_app_row(row) if row else None


async def get_pending_application_for_user(tenant_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE tenant_id = ? AND user_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (tenant_id, user_id),
        )
        row = await cursor.fetchone()
    return _parse_app_row(row) if row else None


async def get_latest_application_for_user(tenant_id: int, user_id: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE tenant_id = ? AND user_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (tenant_id, user_id),
        )
        row = await cursor.fetchone()
    return _parse_app_row(row) if row else None


async def add_admin_message(tenant_id: int, app_id: int, chat_id: int, message_id: int):
    app = await get_application(tenant_id, app_id)
    messages = app["admin_messages"] if app else []
    messages.append({"chat_id": chat_id, "message_id": message_id})
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET admin_messages = ? WHERE id = ? AND tenant_id = ?",
            (json.dumps(messages, ensure_ascii=False), app_id, tenant_id),
        )
        await db.commit()


async def update_status(tenant_id: int, app_id: int, status: str):
    allowed_statuses = {
        "pending",
        "saved",
        "accepted",
        "declined",
        "rejected_hard_filter",
        "rejected_irrelevant",
        "rejected_ai_generated",
        "hired",
        "not_hired",
        "no_show",
    }
    if status not in allowed_statuses:
        raise ValueError("Noto'g'ri nomzod holati.")
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET status = ? WHERE id = ? AND tenant_id = ?",
            (status, app_id, tenant_id),
        )
        await db.commit()


async def transition_application_status(
    tenant_id: int,
    app_id: int,
    new_status: str,
    allowed_from: set[str] | tuple[str, ...],
) -> bool:
    allowed_statuses = {
        "pending",
        "saved",
        "accepted",
        "declined",
        "rejected_hard_filter",
        "rejected_irrelevant",
        "rejected_ai_generated",
        "hired",
        "not_hired",
        "no_show",
    }
    if new_status not in allowed_statuses or not allowed_from:
        raise ValueError("Noto'g'ri nomzod holati.")
    invalid_from = set(allowed_from) - allowed_statuses
    if invalid_from:
        raise ValueError("Noto'g'ri boshlang'ich holat.")

    placeholders = ",".join("?" for _ in allowed_from)
    params = [new_status, app_id, tenant_id, *allowed_from]
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        cursor = await db.execute(
            f"UPDATE applications SET status=? WHERE id=? AND tenant_id=? "
            f"AND status IN ({placeholders})",
            params,
        )
        await db.commit()
        return cursor.rowcount > 0


async def _book_slot_transaction(
    tenant_id: int,
    app_id: int,
    slot: str | None = None,
    capacity: int | None = None,
    *,
    slot_id: int | None = None,
) -> str:
    """Return the atomic booking result for one candidate.

    ``slot_id`` is the production path: the active slot row and its capacity
    are re-read after the write lock is acquired. The legacy label/capacity
    path remains available for integrations and older callers that do not have
    a slot row.
    """
    if slot_id is not None:
        try:
            slot_id = int(slot_id)
        except (TypeError, ValueError):
            return "unavailable"
        if slot_id <= 0:
            return "unavailable"
    else:
        slot = str(slot or "").strip()
        try:
            capacity = int(capacity)
        except (TypeError, ValueError):
            return "unavailable"
        if not slot or len(slot) > 80 or not 1 <= capacity <= 100:
            return "unavailable"

    # The capacity check and the booking update must be in the same write
    # transaction. A plain conditional UPDATE still allows two concurrent
    # candidates to observe the same free seat before either commits.
    async with aiosqlite.connect(SQLITE_PATH, timeout=10) as db:
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            if slot_id is not None:
                cursor = await db.execute(
                    "SELECT label, capacity FROM interview_slots "
                    "WHERE id=? AND tenant_id=? AND active=1 LIMIT 1",
                    (slot_id, tenant_id),
                )
                slot_row = await cursor.fetchone()
                if not slot_row:
                    await db.commit()
                    return "unavailable"
                slot = str(slot_row[0] or "").strip()
                capacity = int(slot_row[1])

            cursor = await db.execute(
                "SELECT selected_slot, status FROM applications "
                "WHERE id=? AND tenant_id=? LIMIT 1",
                (app_id, tenant_id),
            )
            application = await cursor.fetchone()
            if not application:
                await db.commit()
                return "unavailable"

            selected_slot, status = application
            if selected_slot:
                # Repeated Telegram callbacks are harmless, but a candidate
                # cannot silently move an already booked interview elsewhere.
                await db.commit()
                return "already_booked" if selected_slot == slot else "different_slot"
            if status not in {"pending", "saved", "accepted"}:
                await db.commit()
                return "unavailable"

            cursor = await db.execute(
                "SELECT COUNT(*) FROM applications "
                "WHERE tenant_id=? AND selected_slot=?",
                (tenant_id, slot),
            )
            booked = int((await cursor.fetchone())[0] or 0)
            if booked >= capacity:
                await db.commit()
                return "full"

            cursor = await db.execute(
                "UPDATE applications SET selected_slot=?, status='accepted' "
                "WHERE id=? AND tenant_id=? AND selected_slot IS NULL "
                "AND status IN ('pending', 'saved', 'accepted')",
                (slot, app_id, tenant_id),
            )
            await db.commit()
            return "booked" if cursor.rowcount == 1 else "unavailable"
        except Exception:
            await db.rollback()
            raise


async def book_interview_slot(tenant_id: int, app_id: int, slot_id: int) -> str:
    """Book an active interview slot by its database id.

    The returned status lets Telegram handlers distinguish a successful first
    click from a harmless duplicate callback, so confirmations and admin
    notifications are emitted only once.
    """
    return await _book_slot_transaction(tenant_id, app_id, slot_id=slot_id)


async def try_book_slot(
    tenant_id: int,
    app_id: int,
    slot: str,
    capacity: int,
    *,
    slot_id: int | None = None,
) -> bool:
    """Suhbat slotini atomik band qiladi va pipeline holatini sinxronlaydi.

    ``slot_id`` berilganda active slot row tranzaksiya ichida qayta tekshiriladi.
    Eski label/capacity chaqiruvlari esa backward-compatible boolean API sifatida
    ishlaydi; takroriy bir xil band qilish idempotent ravishda ``True`` qaytaradi.
    """
    result = await _book_slot_transaction(
        tenant_id,
        app_id,
        slot,
        capacity,
        slot_id=slot_id,
    )
    return result in {"booked", "already_booked"}


async def count_slot_bookings(tenant_id: int, slot: str) -> int:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM applications WHERE selected_slot = ? AND tenant_id = ?",
            (slot, tenant_id),
        )
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_applications_for_vacancy(
    tenant_id: int, vacancy_key: str, limit: int = 300
) -> list[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE tenant_id = ? AND vacancy_key = ? ORDER BY id DESC LIMIT ?",
            (tenant_id, vacancy_key, limit),
        )
        rows = await cursor.fetchall()
    return [_parse_app_row(r) for r in rows]


async def list_applications(
    tenant_id: int,
    *,
    status: str | None = None,
    search: str | None = None,
    limit: int = 5,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Admin bot ro'yxati uchun sahifalangan arizalar va umumiy soni."""
    where = "tenant_id = ?"
    params: list = [tenant_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    if search:
        term = f"%{search.strip()}%"
        where += (
            " AND (full_name LIKE ? COLLATE NOCASE"
            " OR phone_number LIKE ? COLLATE NOCASE"
            " OR vacancy_title LIKE ? COLLATE NOCASE)"
        )
        params.extend([term, term, term])
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM applications WHERE {where}", params
        )
        total = (await cursor.fetchone())[0]
        cursor = await db.execute(
            f"SELECT * FROM applications WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        )
        rows = await cursor.fetchall()
    return [_parse_app_row(row) for row in rows], total


# ============================= VAKANSIYALAR (admin bot) =============================


def _row_to_vacancy(row) -> dict:
    v = dict(row)
    questions = _json_value(v.get("questions"), [])
    v["questions"] = questions if isinstance(questions, list) else []
    v["profile"] = _json_dict(v.get("profile_json"))
    v["resume_required"] = bool(v["resume_required"])
    v["active"] = bool(v["active"])
    return v


async def list_vacancies(tenant_id: int, active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM vacancies WHERE tenant_id = ?"
    params = [tenant_id]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY created_at DESC"
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [_row_to_vacancy(r) for r in rows]


async def _get_localized_title(
    tenant_id: int, key: str, title_uz: str, lang: str
) -> str:
    if lang != "ru":
        return title_uz

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title_ru FROM vacancies WHERE tenant_id = ? AND key = ?",
            (tenant_id, key),
        )
        row = await cursor.fetchone()

    if row and row["title_ru"]:
        return row["title_ru"]

    from services.ai_scoring import translate_simple_text

    translated = await translate_simple_text(title_uz)
    if not translated:
        return title_uz

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE vacancies SET title_ru = ? WHERE tenant_id = ? AND key = ?",
            (translated, tenant_id, key),
        )
        await db.commit()
    return translated


async def list_vacancies_localized(
    tenant_id: int, lang: str, active_only: bool = True
) -> list[dict]:
    vacancies = await list_vacancies(tenant_id, active_only=active_only)
    if lang != "ru":
        return vacancies
    result = []
    for v in vacancies:
        v = dict(v)
        v["title"] = await _get_localized_title(tenant_id, v["key"], v["title"], lang)
        result.append(v)
    return result


async def get_vacancy(tenant_id: int, key: str) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM vacancies WHERE tenant_id = ? AND key = ?",
            (tenant_id, key),
        )
        row = await cursor.fetchone()
    return _row_to_vacancy(row) if row else None


async def get_vacancy_localized(tenant_id: int, key: str, lang: str) -> dict | None:
    vacancy = await get_vacancy(tenant_id, key)
    if not vacancy or lang != "ru":
        return vacancy

    vacancy = dict(vacancy)
    vacancy["title"] = await _get_localized_title(
        tenant_id, key, vacancy["title"], lang
    )

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT questions_ru, reject_message_ru FROM vacancies WHERE tenant_id = ? AND key = ?",
            (tenant_id, key),
        )
        row = await cursor.fetchone()

    if row and row["questions_ru"]:
        localized_questions = _json_value(row["questions_ru"], [])
        vacancy["questions"] = (
            localized_questions if isinstance(localized_questions, list) else []
        )
        vacancy["reject_message"] = (
            row["reject_message_ru"] or vacancy["reject_message"]
        )
        return vacancy

    from services.ai_scoring import translate_vacancy_content

    translated = await translate_vacancy_content(
        vacancy["questions"], vacancy["reject_message"]
    )
    if not translated:
        logger.warning(
            "Vakansiya (tenant=%s, %s) rus tiliga tarjima qilinmadi.", tenant_id, key
        )
        return vacancy

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE vacancies SET questions_ru = ?, reject_message_ru = ? WHERE tenant_id = ? AND key = ?",
            (
                json.dumps(translated["questions"], ensure_ascii=False),
                translated["reject_message"],
                tenant_id,
                key,
            ),
        )
        await db.commit()

    vacancy["questions"] = translated["questions"]
    vacancy["reject_message"] = translated["reject_message"]
    return vacancy


def make_vacancy_key(title: str) -> str:
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    slug = slug[:40]
    return slug or "vakansiya"


async def create_vacancy(
    *,
    tenant_id: int,
    key: str,
    title: str,
    reject_message: str,
    questions: list,
    resume_required: bool,
    profile: dict | None = None,
    replace_empty_workspace: bool = False,
    interview_slots: list[dict] | None = None,
    interview_location: str | None = None,
    onboarding_industry: str | None = None,
    onboarding_profile: dict | None = None,
) -> None:
    """Create a vacancy and optional onboarding records in one transaction.

    Mini App quick-setup used to write the vacancy, slots, settings and
    onboarding marker in four independent transactions. A timeout or duplicate
    request in the middle left a half-configured tenant. Keeping the optional
    records here makes the whole provisioning operation all-or-nothing.
    """
    from services.plans import get_plan

    key = str(key or "").strip().lower()
    title = str(title or "").strip()
    reject_message = str(reject_message or "").strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", key):
        raise ValueError("Vakansiya kaliti noto'g'ri")
    if not 2 <= len(title) <= 100:
        raise ValueError("Vakansiya nomi 2–100 belgi bo'lishi kerak")
    if not 5 <= len(reject_message) <= 500:
        raise ValueError("Rad javobi 5–500 belgi bo'lishi kerak")
    if not isinstance(questions, list) or not 1 <= len(questions) <= 50:
        raise ValueError("Savollar soni 1–50 oralig'ida bo'lishi kerak")
    for question in questions:
        question_text = (
            question.get("text") if isinstance(question, dict) else question
        )
        if not 1 <= len(str(question_text or "").strip()) <= 1000:
            raise ValueError("Vakansiya savoli 1–1000 belgi bo'lishi kerak")
    if profile is not None and not isinstance(profile, dict):
        raise ValueError("Vakansiya profili noto'g'ri")
    if onboarding_profile is not None and not isinstance(onboarding_profile, dict):
        raise ValueError("Onboarding profili noto'g'ri")
    if onboarding_industry is not None:
        onboarding_industry = str(onboarding_industry).strip()
        if not 2 <= len(onboarding_industry) <= 100:
            raise ValueError("Biznes sohasi 2–100 belgi bo'lishi kerak")
    if interview_location is not None:
        interview_location = str(interview_location).strip() or None
        if interview_location and len(interview_location) > 240:
            raise ValueError("Suhbat manzili juda uzun")

    clean_slots: list[dict] = []
    seen_slot_labels: set[str] = set()
    if interview_slots is not None:
        if not isinstance(interview_slots, list) or len(interview_slots) > 20:
            raise ValueError("Suhbat vaqtlari 0–20 ta bo'lishi kerak")
        for raw_slot in interview_slots:
            if not isinstance(raw_slot, dict):
                raise TypeError("Suhbat vaqti noto'g'ri")
            label = str(raw_slot.get("label") or "").strip()
            if not 3 <= len(label) <= 80:
                raise ValueError("Suhbat vaqti nomi 3–80 belgi bo'lishi kerak")
            try:
                capacity = int(raw_slot.get("capacity", 1))
            except (TypeError, ValueError) as exc:
                raise ValueError("Suhbat sig'imi noto'g'ri") from exc
            if not 1 <= capacity <= 100:
                raise ValueError("Suhbat sig'imi 1–100 oralig'ida bo'lishi kerak")
            label_key = label.casefold()
            if label_key in seen_slot_labels:
                raise InterviewSlotConflict("Bu suhbat vaqti takrorlangan")
            seen_slot_labels.add(label_key)
            clean_slots.append(
                {
                    "label": label,
                    "capacity": capacity,
                    "starts_at": _normalise_slot_start(raw_slot.get("starts_at")),
                }
            )

    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT plan_code, subscription_expires_at FROM tenants WHERE id=?",
                (tenant_id,),
            )
            tenant = await cursor.fetchone()
            if not tenant:
                raise ValueError("Mijoz topilmadi")
            plan = get_plan(tenant[0])
            expires_at = tenant[1]
            expires_dt = _as_utc_datetime(expires_at)
            expired = plan.code not in {"trial", "legacy"} and (
                not expires_dt or expires_dt <= datetime.now(timezone.utc)
            )
            if expired:
                raise VacancyLimitReached("Tarif muddati tugagan")

            if replace_empty_workspace:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM applications WHERE tenant_id=?",
                    (tenant_id,),
                )
                if int((await cursor.fetchone())[0] or 0) == 0:
                    await db.execute(
                        "UPDATE vacancies SET active=0 WHERE tenant_id=?",
                        (tenant_id,),
                    )
                    await db.execute(
                        "DELETE FROM interview_slots WHERE tenant_id=?",
                        (tenant_id,),
                    )
            if plan.vacancy_limit is not None:
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM vacancies WHERE tenant_id=? AND active=1",
                    (tenant_id,),
                )
                used = (await cursor.fetchone())[0]
                if used >= plan.vacancy_limit:
                    raise VacancyLimitReached("Tarifdagi vakansiya limiti tugagan")

            await db.execute(
                "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "
                "resume_required, active, profile_json, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                (
                    tenant_id,
                    key,
                    title,
                    reject_message,
                    json.dumps(questions, ensure_ascii=False),
                    int(resume_required),
                    json.dumps(profile or {}, ensure_ascii=False),
                    created_at,
                ),
            )

            for slot in clean_slots:
                cursor = await db.execute(
                    "SELECT 1 FROM interview_slots WHERE tenant_id=? AND active=1 "
                    "AND LOWER(label)=LOWER(?) LIMIT 1",
                    (tenant_id, slot["label"]),
                )
                if await cursor.fetchone():
                    raise InterviewSlotConflict("Bu suhbat vaqti allaqachon mavjud")
                await db.execute(
                    "INSERT INTO interview_slots "
                    "(tenant_id, label, capacity, starts_at, active, created_at) "
                    "VALUES (?, ?, ?, ?, 1, ?)",
                    (
                        tenant_id,
                        slot["label"],
                        slot["capacity"],
                        slot["starts_at"],
                        created_at,
                    ),
                )

            if interview_location is not None:
                await db.execute(
                    "INSERT INTO interview_settings "
                    "(tenant_id, location_text) VALUES (?, ?) "
                    "ON CONFLICT(tenant_id) DO UPDATE SET location_text=excluded.location_text",
                    (tenant_id, interview_location),
                )
            elif replace_empty_workspace:
                await db.execute(
                    "DELETE FROM interview_settings WHERE tenant_id=?",
                    (tenant_id,),
                )

            if onboarding_industry is not None or onboarding_profile is not None:
                await db.execute(
                    "UPDATE tenants SET industry=COALESCE(?, industry), "
                    "onboarding_profile=COALESCE(?, onboarding_profile), "
                    "onboarding_completed_at=? WHERE id=?",
                    (
                        onboarding_industry,
                        json.dumps(onboarding_profile, ensure_ascii=False)
                        if onboarding_profile is not None
                        else None,
                        created_at,
                        tenant_id,
                    ),
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def set_vacancy_active(tenant_id: int, key: str, active: bool) -> bool:
    """Vakansiyani atomik faollashtiradi/faolsizlantiradi va quota bypassni yopadi."""
    from services.plans import get_plan

    now = datetime.now(timezone.utc)
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT active FROM vacancies WHERE tenant_id=? AND key=?",
                (tenant_id, key),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return False
            current = bool(row[0])
            if current == bool(active):
                await db.commit()
                return True

            if active:
                cursor = await db.execute(
                    "SELECT plan_code, subscription_expires_at FROM tenants WHERE id=?",
                    (tenant_id,),
                )
                tenant = await cursor.fetchone()
                if not tenant:
                    raise ValueError("Mijoz topilmadi")
                plan = get_plan(tenant[0])
                expires_at = _as_utc_datetime(tenant[1])
                expired = bool(
                    plan.code not in {"trial", "legacy"}
                    and (not expires_at or expires_at <= now)
                )
                if expired:
                    raise VacancyLimitReached("Tarif muddati tugagan")
                if plan.vacancy_limit is not None:
                    cursor = await db.execute(
                        "SELECT COUNT(*) FROM vacancies WHERE tenant_id=? AND active=1",
                        (tenant_id,),
                    )
                    used = (await cursor.fetchone())[0]
                    if used >= plan.vacancy_limit:
                        raise VacancyLimitReached("Tarifdagi vakansiya limiti tugagan")

            cursor = await db.execute(
                "UPDATE vacancies SET active=? WHERE tenant_id=? AND key=?",
                (int(bool(active)), tenant_id, key),
            )
            await db.commit()
            return cursor.rowcount > 0
        except Exception:
            await db.rollback()
            raise


async def update_vacancy(tenant_id: int, key: str, **fields) -> None:
    if not fields:
        return
    allowed_fields = {
        "title",
        "reject_message",
        "questions",
        "resume_required",
        "active",
        "profile",
    }
    unknown_fields = set(fields) - allowed_fields
    if unknown_fields:
        raise ValueError("Noto'g'ri vakansiya maydoni.")
    set_clauses, values = [], []
    for field, value in fields.items():
        if field == "questions":
            value = json.dumps(value, ensure_ascii=False)
        elif field == "profile":
            field = "profile_json"
            value = json.dumps(value or {}, ensure_ascii=False)
        elif field in ("resume_required", "active"):
            value = int(value)
        set_clauses.append(f"{field} = ?")
        values.append(value)

    if "questions" in fields or "reject_message" in fields:
        set_clauses += ["questions_ru = NULL", "reject_message_ru = NULL"]
    if "title" in fields:
        set_clauses.append("title_ru = NULL")

    values += [tenant_id, key]
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            f"UPDATE vacancies SET {', '.join(set_clauses)} WHERE tenant_id = ? AND key = ?",
            values,
        )
        await db.commit()


async def delete_vacancy(tenant_id: int, key: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "DELETE FROM vacancies WHERE tenant_id = ? AND key = ?", (tenant_id, key)
        )
        await db.commit()


# ============================= SUHBAT VAQTLARI (admin bot) =============================


async def list_interview_slots(tenant_id: int, active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM interview_slots WHERE tenant_id = ?"
    params = [tenant_id]
    if active_only:
        query += " AND active = 1"
    query += " ORDER BY id ASC"
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_interview_slot(
    tenant_id: int, label: str, capacity: int = 1, starts_at: str | None = None
) -> int:
    label = str(label or "").strip()
    if not 3 <= len(label) <= 80:
        raise ValueError("Suhbat vaqti nomi 3–80 belgi bo'lishi kerak")
    try:
        capacity = int(capacity)
    except (TypeError, ValueError) as exc:
        raise ValueError("Suhbat sig'imi noto'g'ri") from exc
    if not 1 <= capacity <= 100:
        raise ValueError("Suhbat sig'imi 1–100 oralig'ida bo'lishi kerak")
    starts_at = _normalise_slot_start(starts_at)
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT 1 FROM interview_slots WHERE tenant_id=? AND active=1 "
                "AND LOWER(label)=LOWER(?) LIMIT 1",
                (tenant_id, label),
            )
            if await cursor.fetchone():
                raise InterviewSlotConflict("Bu suhbat vaqti allaqachon mavjud")
            cursor = await db.execute(
                "INSERT INTO interview_slots (tenant_id, label, capacity, starts_at, active, created_at) "
                "VALUES (?, ?, ?, ?, 1, ?)",
                (tenant_id, label, capacity, starts_at, created_at),
            )
            await db.commit()
            return cursor.lastrowid
        except Exception:
            await db.rollback()
            raise


async def delete_interview_slot(tenant_id: int, slot_id: int) -> bool:
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT label FROM interview_slots WHERE id=? AND tenant_id=?",
                (slot_id, tenant_id),
            )
            row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return False
            label = row[0]
            cursor = await db.execute(
                "SELECT COUNT(*) FROM applications WHERE tenant_id=? AND selected_slot=?",
                (tenant_id, label),
            )
            booked = (await cursor.fetchone())[0]
            if booked:
                raise InterviewSlotBooked("Bu vaqtni nomzod tanlagan")
            cursor = await db.execute(
                "DELETE FROM interview_slots WHERE id=? AND tenant_id=?",
                (slot_id, tenant_id),
            )
            await db.commit()
            return cursor.rowcount > 0
        except Exception:
            await db.rollback()
            raise


async def get_available_interview_slots(tenant_id: int) -> list[dict]:
    slots = await list_interview_slots(tenant_id, active_only=True)
    result = []
    for slot in slots:
        booked = await count_slot_bookings(tenant_id, slot["label"])
        if booked < slot["capacity"]:
            result.append({**slot, "booked": booked})
    return result


async def get_interview_settings(tenant_id: int) -> dict:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM interview_settings WHERE tenant_id = ?", (tenant_id,)
        )
        row = await cursor.fetchone()
    if not row:
        return {
            "location_text": None,
            "location_lat": None,
            "location_lng": None,
            "interviewer_name": None,
            "interviewer_phone": None,
            "notes": None,
        }
    return dict(row)


async def update_interview_settings(tenant_id: int, **fields):
    if not fields:
        return
    allowed_fields = {
        "location_text",
        "location_lat",
        "location_lng",
        "interviewer_name",
        "interviewer_phone",
        "notes",
    }
    unknown = set(fields) - allowed_fields
    if unknown:
        raise ValueError("Noto'g'ri suhbat sozlamasi")
    current = await get_interview_settings(tenant_id)
    merged = {**current, **fields}
    text_limits = {
        "location_text": 240,
        "interviewer_name": 80,
        "interviewer_phone": 32,
        "notes": 500,
    }
    for field, limit in text_limits.items():
        value = merged.get(field)
        value = str(value).strip() if value not in (None, "") else None
        if value and len(value) > limit:
            raise ValueError(f"{field} juda uzun")
        merged[field] = value

    for field in ("location_lat", "location_lng"):
        value = merged.get(field)
        if value in (None, ""):
            merged[field] = None
            continue
        try:
            merged[field] = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Lokatsiya koordinatasi noto'g'ri") from exc
    lat, lng = merged.get("location_lat"), merged.get("location_lng")
    if (lat is None) != (lng is None):
        raise ValueError("Lokatsiya uchun latitude va longitude ikkalasi ham kerak")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise ValueError("Lokatsiya koordinatasi chegaradan tashqarida")

    phone = merged.get("interviewer_phone")
    if phone and not re.fullmatch(r"[+()\-\s\d]{5,32}", phone):
        raise ValueError("Intervyuchi telefoni noto'g'ri")

    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                """
                INSERT INTO interview_settings
                    (tenant_id, location_text, location_lat, location_lng, interviewer_name, interviewer_phone, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id) DO UPDATE SET
                    location_text = excluded.location_text, location_lat = excluded.location_lat,
                    location_lng = excluded.location_lng, interviewer_name = excluded.interviewer_name,
                    interviewer_phone = excluded.interviewer_phone, notes = excluded.notes
                """,
                (
                    tenant_id,
                    merged.get("location_text"),
                    merged.get("location_lat"),
                    merged.get("location_lng"),
                    merged.get("interviewer_name"),
                    merged.get("interviewer_phone"),
                    merged.get("notes"),
                ),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise


async def update_tenant_onboarding(
    tenant_id: int, *, industry: str, profile: dict, completed: bool = True
) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE tenants SET industry=?, onboarding_profile=?, onboarding_completed_at=? WHERE id=?",
            (
                industry,
                json.dumps(profile or {}, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat() if completed else None,
                tenant_id,
            ),
        )
        await db.commit()


async def deactivate_empty_vacancies(tenant_id: int) -> None:
    """Arizasi bo'lmagan eski demo vakansiyalarni onboarding oldidan yopadi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE vacancies SET active=0 WHERE tenant_id=? AND key NOT IN "
            "(SELECT DISTINCT vacancy_key FROM applications WHERE tenant_id=?)",
            (tenant_id, tenant_id),
        )
        await db.commit()


async def clear_unbooked_interview_slots(tenant_id: int) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "DELETE FROM interview_slots WHERE tenant_id=? AND label NOT IN "
            "(SELECT DISTINCT selected_slot FROM applications WHERE tenant_id=? AND selected_slot IS NOT NULL)",
            (tenant_id, tenant_id),
        )
        await db.commit()


async def list_funnel_applications(
    tenant_id: int, *, days: int = 30, vacancy_key: str | None = None
) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
    sql = "SELECT * FROM applications WHERE tenant_id=? AND created_at>=?"
    params: list = [tenant_id, cutoff]
    if vacancy_key:
        sql += " AND vacancy_key=?"
        params.append(vacancy_key)
    sql += " ORDER BY id DESC"
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        rows = await (await db.execute(sql, params)).fetchall()
    return [_parse_app_row(row) for row in rows]


async def list_interview_followup_candidates() -> list[dict]:
    now = datetime.now(timezone.utc)
    lower = (now - timedelta(hours=24)).isoformat()
    upper = (now + timedelta(hours=26)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT a.id AS app_id, a.tenant_id, a.user_id, a.full_name, a.vacancy_title, "
            "a.lang, a.selected_slot, a.status, s.starts_at, t.bot_token, t.admin_bot_token, "
            "t.admin_user_ids, t.plan_code, t.subscription_expires_at FROM applications a "
            "JOIN interview_slots s ON s.tenant_id=a.tenant_id AND s.label=a.selected_slot "
            "JOIN tenants t ON t.id=a.tenant_id "
            "WHERE a.status='accepted' AND s.starts_at IS NOT NULL "
            "AND s.starts_at>=? AND s.starts_at<=? AND t.status='active'",
            (lower, upper),
        )
        rows = await cursor.fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["admin_user_ids"] = _tenant_from_row(
            {"admin_user_ids": item.get("admin_user_ids")}
        )["admin_user_ids"]
        result.append(item)
    return result


# ============================= STATISTIKA (admin bot) =============================

_TERMINAL_REJECTED_STATUSES = {
    "rejected_hard_filter",
    "rejected_irrelevant",
    "rejected_ai_generated",
    "declined",
}


async def get_overall_stats(tenant_id: int) -> dict:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM applications WHERE tenant_id = ? GROUP BY status",
            (tenant_id,),
        )
        rows = await cursor.fetchall()

    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    rejected_total = sum(by_status.get(s, 0) for s in _TERMINAL_REJECTED_STATUSES)

    return {
        "total": total,
        "pending": by_status.get("pending", 0),
        "accepted": by_status.get("accepted", 0),
        "declined_by_admin": by_status.get("declined", 0),
        "rejected_hard_filter": by_status.get("rejected_hard_filter", 0),
        "rejected_irrelevant": by_status.get("rejected_irrelevant", 0),
        "rejected_ai_generated": by_status.get("rejected_ai_generated", 0),
        "rejected_total": rejected_total,
        "by_status": by_status,
    }


async def get_vacancy_stats(tenant_id: int) -> list[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT vacancy_key, vacancy_title, status, COUNT(*) FROM applications "
            "WHERE tenant_id = ? GROUP BY vacancy_key, vacancy_title, status",
            (tenant_id,),
        )
        rows = await cursor.fetchall()

    per_vacancy: dict[str, dict] = {}
    for vacancy_key, vacancy_title, status, count in rows:
        entry = per_vacancy.setdefault(
            vacancy_key,
            {
                "vacancy_key": vacancy_key,
                "vacancy_title": vacancy_title,
                "total": 0,
                "pending": 0,
                "accepted": 0,
                "rejected": 0,
            },
        )
        entry["total"] += count
        if status == "pending":
            entry["pending"] += count
        elif status == "accepted":
            entry["accepted"] += count
        elif status in _TERMINAL_REJECTED_STATUSES:
            entry["rejected"] += count

    return sorted(per_vacancy.values(), key=lambda e: -e["total"])


# ============================= TOLOV BUYURTMALARI =============================


async def create_payment_order(
    tenant_id: int,
    order_code: str,
    base_amount: int,
    amount: int,
    expires_at: str,
    plan_code: str = "start",
    billing_months: int = 1,
) -> int:
    from services.plans import PUBLIC_PLAN_CODES, get_plan

    try:
        base_amount = int(base_amount)
        amount = int(amount)
        billing_months = int(billing_months)
    except (TypeError, ValueError) as exc:
        raise ValueError("To'lov summasi yoki muddati noto'g'ri") from exc
    plan_code = str(plan_code or "").strip().lower()
    if plan_code not in PUBLIC_PLAN_CODES:
        raise ValueError("Noto'g'ri tarif")
    plan = get_plan(plan_code)
    # This low-level creator must enforce the same pricing invariant as the
    # payment service.  Subscription activation keeps support for historical
    # multi-month rows, but a new order cannot buy multiple months for one
    # monthly amount.
    if billing_months != 1:
        raise ValueError("Hozircha faqat 1 oylik to'lov buyurtmasi mavjud")
    if not 0 < base_amount <= plan.price or amount < base_amount:
        raise ValueError("To'lov summasi tarifga mos emas")
    if not _as_utc_datetime(expires_at):
        raise ValueError("To'lov muddati noto'g'ri")
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            cursor = await db.execute(
                "SELECT 1 FROM tenants WHERE id=? LIMIT 1", (tenant_id,)
            )
            if not await cursor.fetchone():
                raise ValueError("Mijoz topilmadi")
            cursor = await db.execute(
                "INSERT INTO payment_orders (tenant_id, order_code, base_amount, amount, plan_code, "
                "billing_months, status, created_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_payment', ?, ?)",
                (
                    tenant_id,
                    order_code,
                    base_amount,
                    amount,
                    plan_code,
                    billing_months,
                    created_at,
                    expires_at,
                ),
            )
            await db.commit()
            return cursor.lastrowid
        except Exception:
            await db.rollback()
            raise


async def cancel_open_payment_orders_for_tenant(tenant_id: int) -> None:
    """Mijoz yangi buyurtma yaratmoqchi bo'lsa, avvalgi ochiq (hali
    to'lanmagan) buyurtmalarini bekor qiladi — bir vaqtda faqat bitta
    ochiq buyurtma bo'lishi kerak."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET status = 'cancelled' "
            "WHERE tenant_id = ? AND status = 'awaiting_payment'",
            (tenant_id,),
        )
        await db.commit()


async def get_open_payment_order_by_amount(amount: int) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'awaiting_payment' AND amount = ? LIMIT 1",
            (amount,),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_open_payment_orders_by_amount(amount: int) -> list[dict]:
    """Aniq summali ochiq buyurtmalarni 24 soatlik to'lov grace-periodi bilan qaytaradi.

    UI'dagi 20 daqiqa noyob summani band qilish muddati. Bank o'tkazmasi kechiksa,
    haqiqiy tushgan pul yo'qolib qolmasligi kerak.
    """
    grace_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'awaiting_payment' "
            "AND amount = ? AND expires_at > ?",
            (amount, grace_cutoff),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def list_open_payment_orders() -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'awaiting_payment' AND expires_at > ?",
            (now,),
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def try_approve_payment_order(order_id: int) -> bool:
    """Atomik tasdiqlash — parallel kelgan ikkinchi bildirishnoma bir xil
    buyurtmani ikki marta faollashtira olmasligi uchun."""
    decided_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "UPDATE payment_orders SET status = 'approved', decided_at = ? "
            "WHERE id = ? AND status = 'awaiting_payment'",
            (decided_at, order_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_payment_order_by_code(order_code: str) -> dict | None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE UPPER(order_code)=UPPER(?) LIMIT 1",
            (order_code.strip(),),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def approve_payment_order_manually(order_id: int) -> bool:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "UPDATE payment_orders SET status='approved', decided_at=? "
            "WHERE id=? AND status IN ('awaiting_payment', 'needs_review')",
            (datetime.now(timezone.utc).isoformat(), order_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_payment_order_needs_review(
    order_id: int, notification_text: str, *, keep_approved: bool = False
) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET status = CASE WHEN status='approved' AND ? "
            "THEN 'approved' ELSE 'needs_review' END, notification_text = ? WHERE id = ?",
            (int(keep_approved), notification_text, order_id),
        )
        await db.commit()


async def list_unnotified_approved_orders(hours: int | None = None) -> list[dict]:
    cutoff = ((datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
              if hours is not None else "")
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'approved' "
            "AND subscription_activated_at IS NOT NULL "
            "AND customer_notified_at IS NULL AND decided_at >= ? ORDER BY decided_at",
            (cutoff,),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def claim_customer_payment_receipt(
    order_id: int,
    admin_user_id: int,
    *,
    stale_after_minutes: int = 10,
) -> bool:
    """Bitta order/admin chekini parallel workerlar orasida atomik band qiladi."""
    now = datetime.now(timezone.utc)
    stale_before = (now - timedelta(minutes=max(1, stale_after_minutes))).isoformat()
    now_iso = now.isoformat()
    async with aiosqlite.connect(SQLITE_PATH, timeout=10) as db:
        await db.execute("PRAGMA busy_timeout=10000")
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO payment_customer_receipts "
                "(order_id, admin_user_id, status) VALUES (?, ?, 'pending')",
                (order_id, admin_user_id),
            )
            cursor = await db.execute(
                "UPDATE payment_customer_receipts SET status='sending', claimed_at=? "
                "WHERE order_id=? AND admin_user_id=? AND "
                "(status='pending' OR (status='sending' AND claimed_at < ?))",
                (now_iso, order_id, admin_user_id, stale_before),
            )
            await db.commit()
            return cursor.rowcount == 1
        except Exception:
            await db.rollback()
            raise


async def release_customer_payment_receipt_claim(
    order_id: int, admin_user_id: int
) -> None:
    """Telegram yuborishi yiqilsa aynan shu adminni qayta urinishga ochadi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_customer_receipts SET status='pending', claimed_at=NULL "
            "WHERE order_id=? AND admin_user_id=? AND status='sending'",
            (order_id, admin_user_id),
        )
        await db.commit()


async def mark_customer_payment_receipt_sent(
    order_id: int, admin_user_id: int
) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_customer_receipts SET status='sent', sent_at=?, claimed_at=NULL "
            "WHERE order_id=? AND admin_user_id=? AND status='sending'",
            (datetime.now(timezone.utc).isoformat(), order_id, admin_user_id),
        )
        await db.commit()


async def all_customer_payment_receipts_sent(
    order_id: int, admin_user_ids: list[int]
) -> bool:
    admin_ids = sorted({int(value) for value in admin_user_ids})
    if not admin_ids:
        return False
    placeholders = ",".join("?" for _ in admin_ids)
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM payment_customer_receipts "
            f"WHERE order_id=? AND status='sent' AND admin_user_id IN ({placeholders})",
            (order_id, *admin_ids),
        )
        row = await cursor.fetchone()
    return bool(row and int(row[0]) == len(admin_ids))


async def list_approved_orders_without_subscription(limit: int = 100) -> list[dict]:
    """Return approved orders whose one-time activation marker is missing."""
    limit = max(1, min(int(limit or 100), 500))
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status='approved' "
            "AND subscription_activated_at IS NULL ORDER BY decided_at, id LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def mark_customer_payment_notified(order_code: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET customer_notified_at = ? WHERE order_code = ?",
            (datetime.now(timezone.utc).isoformat(), order_code),
        )
        await db.commit()


async def was_notification_seen_recently(text_hash: str, minutes: int = 30) -> bool:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT received_at FROM payment_notifications_seen WHERE hash = ?",
            (text_hash,),
        )
        row = await cursor.fetchone()
    if not row:
        return False
    seen_at = _as_utc_datetime(row["received_at"])
    if seen_at is None:
        return False
    return (datetime.now(timezone.utc) - seen_at) < timedelta(minutes=minutes)


async def record_seen_notification(text_hash: str, amount: int) -> None:
    received_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "INSERT INTO payment_notifications_seen (hash, amount, received_at) VALUES (?, ?, ?) "
            "ON CONFLICT(hash) DO UPDATE SET amount = excluded.amount, received_at = excluded.received_at",
            (text_hash, amount, received_at),
        )
        await db.commit()


async def forget_payment_notification(text_hash: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "DELETE FROM payment_notifications_seen WHERE hash = ?", (text_hash,)
        )
        await db.commit()


async def clear_old_payment_notifications(days: int = 7) -> None:
    """Deduplikatsiyani saqlab, faqat eskirgan notification hashlarini tozalash."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "DELETE FROM payment_notifications_seen WHERE received_at < ?", (cutoff,)
        )
        await db.commit()
