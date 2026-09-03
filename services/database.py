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
from datetime import datetime, timedelta, timezone

import aiosqlite

from config import SQLITE_PATH

logger = logging.getLogger("janob_hr_bot")


class ApplicationLimitReached(RuntimeError):
    """Tarif ariza limiti atomik saqlash paytida tugagan."""


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
    customer_notified_at TEXT
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


async def create_tenant(
    company_name: str,
    bot_token: str,
    admin_bot_token: str,
    admin_user_ids: list[int],
    contact_name: str = "",
    contact_phone: str = "",
    contact_username: str = "",
) -> int:
    """Yangi mijoz yaratadi va unga standart 3 ta namunaviy vakansiyani urug'laydi.
    Ikkita alohida token oladi: `bot_token` — nomzod-bot uchun, `admin_bot_token` —
    faqat shu mijozning administratorlari ishlatadigan Admin panel-bot uchun."""
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
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

        for v in _DEFAULT_VACANCIES:
            await db.execute(
                "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "
                "resume_required, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (
                    tenant_id,
                    v["key"],
                    v["title"],
                    v["reject_message"],
                    json.dumps(v["questions"], ensure_ascii=False),
                    int(v["resume_required"]),
                    created_at,
                ),
            )
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
    t = dict(row)
    t["admin_user_ids"] = json.loads(t["admin_user_ids"])
    try:
        t["onboarding_profile"] = json.loads(t.get("onboarding_profile") or "{}")
    except (TypeError, json.JSONDecodeError):
        t["onboarding_profile"] = {}
    return t


async def get_tenant_by_role_token(token: str) -> tuple[dict, str] | None:
    """Berilgan token — nomzod-bot yoki Admin panel-bot tokenlaridan qaysi biriga
    mos kelishini tekshiradi. Topilsa (mijoz, rol) qaytaradi, rol — "candidate"
    yoki "admin". Hech biriga mos kelmasa None qaytaradi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tenants WHERE bot_token = ?", (token,))
        row = await cursor.fetchone()
        if row:
            t = dict(row)
            t["admin_user_ids"] = json.loads(t["admin_user_ids"])
            return t, "candidate"

        cursor = await db.execute(
            "SELECT * FROM tenants WHERE admin_bot_token = ?", (token,)
        )
        row = await cursor.fetchone()
        if row:
            t = dict(row)
            t["admin_user_ids"] = json.loads(t["admin_user_ids"])
            return t, "admin"

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
        t = dict(row)
        t["admin_user_ids"] = json.loads(t["admin_user_ids"])
        try:
            t["onboarding_profile"] = json.loads(t.get("onboarding_profile") or "{}")
        except (TypeError, json.JSONDecodeError):
            t["onboarding_profile"] = {}
        result.append(t)
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

    renewals = [
        item for item in customers
        if item["status"] == "active"
        and item.get("subscription_expires_at")
        and item["subscription_expires_at"] <= renewal_cutoff
    ]
    for item in renewals:
        expires = datetime.fromisoformat(item["subscription_expires_at"])
        item["days_left"] = max(-999, (expires.date() - now.date()).days)
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
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(telegram_user_id, contact_phone) DO UPDATE SET "
            "contact_name=excluded.contact_name, contact_username=excluded.contact_username, "
            "company_name=excluded.company_name, hiring_problem=excluded.hiring_problem, "
            "current_process=excluded.current_process, desired_result=excluded.desired_result, "
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
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE tenant_id=? AND UPPER(order_code)=UPPER(?) LIMIT 1",
            (tenant_id, order_code.strip()),
        )
        row = await cursor.fetchone()
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
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT p.*, t.company_name, t.contact_phone FROM payment_orders p "
            "JOIN tenants t ON t.id=p.tenant_id "
            "WHERE p.status='awaiting_payment' AND p.created_at <= ? "
            "ORDER BY p.created_at LIMIT 100",
            (cutoff,),
        )
        return [dict(row) for row in await cursor.fetchall()]


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
        item = dict(row)
        item["admin_user_ids"] = json.loads(item["admin_user_ids"])
        result.append(item)
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
        item = dict(row)
        item["admin_user_ids"] = json.loads(item["admin_user_ids"])
        result.append(item)
    return result


async def update_tenant_status(
    tenant_id: int, status: str, bot_username: str | None = None
) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        if bot_username is not None:
            await db.execute(
                "UPDATE tenants SET status = ?, bot_username = ? WHERE id = ?",
                (status, bot_username, tenant_id),
            )
        else:
            await db.execute(
                "UPDATE tenants SET status = ? WHERE id = ?", (status, tenant_id)
            )
        await db.commit()


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
    expired = bool(
        plan.code not in {"trial", "legacy"}
        and (not expires_at or expires_at <= datetime.now(timezone.utc).isoformat())
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
    tenant = await get_tenant(tenant_id)
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
    try:
        current_expiry = datetime.fromisoformat(
            tenant.get("subscription_expires_at") or ""
        )
    except (AttributeError, TypeError, ValueError):
        current_expiry = now
    expires = max(now, current_expiry) + timedelta(days=30 * max(1, months))
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE tenants SET plan_code = ?, subscription_started_at = ?, "
            "subscription_expires_at = ? WHERE id = ?",
            (plan_code, now.isoformat(), expires.isoformat(), tenant_id),
        )
        await db.commit()


# ============================= ARIZALAR (applications) =============================


def _parse_app_row(row) -> dict:
    app = dict(row)
    app["answers"] = json.loads(app["answers"])
    app["ai_scores"] = json.loads(app["ai_scores"])
    app["admin_messages"] = json.loads(app.get("admin_messages") or "[]")
    app["ai_suspect_flags"] = json.loads(app.get("ai_suspect_flags") or "[]")
    app["voice_answers"] = json.loads(app.get("voice_answers") or "{}")
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


async def try_book_slot(tenant_id: int, app_id: int, slot: str, capacity: int) -> bool:
    """Suhbat slotini atomik band qiladi va pipeline holatini sinxronlaydi.

    Yuqori ball sabab admin qaroridan oldin slot taklif qilingan nomzod slotni
    tanlasa, u endi mantiqan `accepted` bo'ladi. Bir xil tugmani qayta bosish
    esa idempotent: o'z sloti to'lib qolgan bo'lsa ham muvaffaqiyat qaytadi.
    """
    async with aiosqlite.connect(SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        cursor = await db.execute(
            """
            UPDATE applications
            SET selected_slot = ?, status = 'accepted'
            WHERE id = ? AND tenant_id = ?
              AND status IN ('pending', 'saved', 'accepted')
              AND (
                    selected_slot = ?
                    OR (SELECT COUNT(*) FROM applications
                        WHERE selected_slot = ? AND tenant_id = ?) < ?
                  )
            """,
            (slot, app_id, tenant_id, slot, slot, tenant_id, capacity),
        )
        await db.commit()
        return cursor.rowcount > 0


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
    v["questions"] = json.loads(v["questions"])
    try:
        v["profile"] = json.loads(v.get("profile_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        v["profile"] = {}
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
        vacancy["questions"] = json.loads(row["questions_ru"])
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
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
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
        await db.commit()


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
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO interview_slots (tenant_id, label, capacity, starts_at, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (tenant_id, label, capacity, starts_at, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_interview_slot(tenant_id: int, slot_id: int):
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "DELETE FROM interview_slots WHERE id = ? AND tenant_id = ?",
            (slot_id, tenant_id),
        )
        await db.commit()


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
    current = await get_interview_settings(tenant_id)
    merged = {**current, **fields}
    async with aiosqlite.connect(SQLITE_PATH) as db:
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
            "t.admin_user_ids FROM applications a "
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
        try:
            item["admin_user_ids"] = json.loads(item.get("admin_user_ids") or "[]")
        except (TypeError, json.JSONDecodeError):
            item["admin_user_ids"] = []
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
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
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
    order_id: int, notification_text: str
) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET status = 'needs_review', notification_text = ? WHERE id = ?",
            (notification_text, order_id),
        )
        await db.commit()


async def list_unnotified_approved_orders(hours: int = 24) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'approved' "
            "AND customer_notified_at IS NULL AND decided_at >= ? ORDER BY decided_at",
            (cutoff,),
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
    seen_at = datetime.fromisoformat(row["received_at"])
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
