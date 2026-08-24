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
from typing import Optional

import aiosqlite

from config import SQLITE_PATH

logger = logging.getLogger("janob_hr_bot")

_CREATE_TENANTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    bot_token TEXT NOT NULL UNIQUE,
    bot_username TEXT,
    admin_bot_token TEXT UNIQUE,
    admin_bot_username TEXT,
    admin_user_ids TEXT NOT NULL DEFAULT '[]',
    contact_phone TEXT,
    contact_full_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
"""

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
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
_CREATE_SALES_LEADS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sales_leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id INTEGER NOT NULL,
    telegram_username TEXT,
    phone TEXT,
    full_name TEXT,
    company_name TEXT,
    conversation_summary TEXT,
    status TEXT NOT NULL DEFAULT 'yangi',
    tenant_id INTEGER,
    created_at TEXT NOT NULL
);
"""

_CREATE_PAYMENT_ORDERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS payment_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    order_code TEXT NOT NULL UNIQUE,
    base_amount INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_payment',
    notification_text TEXT,
    notify_bot_token TEXT,
    notify_chat_id INTEGER,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    decided_at TEXT
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

# Bot /start bosilgan HAR bir holatni yozib boradi — "voronka" (nechta kishi
# boshladi, nechtasi ariza topshirdi) hisoblash uchun.
_CREATE_BOT_STARTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bot_starts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    started_at TEXT NOT NULL
);
"""

# Yangi mijoz qo'shilganda, unga boshlang'ich nuqta sifatida urug'lanadigan
# 3 ta namunaviy vakansiya (avvalgi bir-mijozli tizimdan meros).
_DEFAULT_VACANCIES = [
    {
        "key": "sales", "title": "🧑‍💼 Sotuv menejeri",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha ushbu tajriba talablarimizga to'liq mos "
            "kelmayapti, shu sababli ushbu bosqichda davom eta olmaymiz. "
            "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
        ),
        "resume_required": False,
        "questions": [
            {"key": "experience", "text": "Oldin sotuv sohasida ishlaganmisiz? (Ha/Yo'q)", "hard_filter": True},
            {"key": "experience_details", "text": "Qayerda va qancha muddat sotuv qilgansiz? Qisqacha yozing."},
            {"key": "crm", "text": "Qanday CRM tizimlarida ishlagansiz? (Bitrix24, amoCRM va h.k.)"},
            {"key": "scorecard_plan", "text": (
                "Bizning kompaniya keyingi chorakda sotuvni kamida $20,000 ga oshirishi kerak. "
                "Ishga kelganingizdan keyin birinchi 30 kun ichida bunga qanday hissa qo'shasiz? "
                "Aniq rejangizni 3 ta qadamda yozing."
            ), "ai_score": True},
            {"key": "achievement", "text": (
                "Oldingi ish joyingizda erishgan eng katta va aniq yutug'ingizni yozing "
                "(iloji bo'lsa, raqamlar bilan)."
            ), "ai_score": True},
            {"key": "mistake_lesson", "text": (
                "Ishingizda yo'l qo'ygan eng jiddiy xatoyingiz nima bo'lgan va undan qanday dars oldingiz?"
            ), "ai_score": True},
            {"key": "hard_client", "text": "Qiyin mijoz bilan qanday ishlaysiz? Bitta real holatni yozib bering.", "ai_score": True},
            {"key": "teamwork", "text": "Jamoada ishlash tajribangizni bitta real misol bilan tushuntiring.", "ai_score": True},
            {"key": "motivation", "text": "Nega aynan bizning kompaniyada ishlashni xohlaysiz?", "ai_score": True},
            {"key": "salary_expectation", "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)"},
        ],
    },
    {
        "key": "designer", "title": "🎨 Dizayner",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
            "Portfolioingizni boyitib, keyinroq qayta murojaat qilishingiz mumkin. Omad! 🙏"
        ),
        "resume_required": True,
        "questions": [
            {"key": "tool", "text": "Figma yoki Adobe (Photoshop/Illustrator) dasturlaridan qaysi birida ishlaysiz?"},
            {"key": "portfolio", "text": "Portfolio (ishlaringiz namunasi) linkini yuboring.", "hard_filter": True},
            {"key": "scorecard_output", "text": (
                "Bizning brend uchun ijtimoiy tarmoqlarda oyiga kamida 20 ta post dizayni "
                "tayyorlashingiz kerak bo'ladi. Birinchi haftada ishni qanday tashkil qilasiz "
                "va sifatni qanday ta'minlaysiz?"
            ), "ai_score": True},
            {"key": "achievement", "text": (
                "Eng faxrlanadigan loyihangizni tasvirlab bering — u qanday aniq natija "
                "(masalan, mijoz sotuvi, engagement o'sishi) keltirdi?"
            ), "ai_score": True},
            {"key": "mistake_lesson", "text": "Dizaynda yo'l qo'ygan eng jiddiy xatoyingiz nima bo'lgan va undan qanday dars oldingiz?", "ai_score": True},
            {"key": "style", "text": "Sizga qaysi dizayn yo'nalishi (uslub) yaqinroq va nega?", "ai_score": True},
            {"key": "deadline_handling", "text": "Bir vaqtning o'zida bir nechta muhim topshiriq kelib qolsa, ularni qanday tartibga solasiz?", "ai_score": True},
            {"key": "feedback_handling", "text": "Mijoz yoki rahbar ishingizni qattiq tanqid qilsa, munosabatingiz qanday bo'ladi?", "ai_score": True},
            {"key": "salary_expectation", "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)"},
        ],
    },
    {
        "key": "smm", "title": "📱 SMM mutaxassis",
        "reject_message": (
            "Anketangiz uchun rahmat! Hozircha tajribangiz talablarimizga mos kelmayapti. "
            "Boshqa vakansiyalarimizni kuzatib boring — omad tilaymiz! 🙏"
        ),
        "resume_required": False,
        "questions": [
            {"key": "platforms", "text": "Qaysi platformalarda (Instagram, Telegram, TikTok) tajribangiz bor?"},
            {"key": "content_plan", "text": "Kontent-reja tuzish tajribangiz bormi? (Ha/Yo'q)", "hard_filter": True},
            {"key": "scorecard_growth", "text": (
                "Bizning Instagram sahifamizni 3 oy ichida kamida 5,000 ta yangi obunachiga "
                "olib chiqishingiz kerak. Buni qanday aniq qadamlar bilan amalga oshirasiz?"
            ), "ai_score": True},
            {"key": "cases", "text": (
                "Oldingi ishlaringizdan eng yaxshi natija bergan case'ni raqamlar bilan yozib "
                "bering (masalan: \"Reels 100,000 ko'rishga yetdi\")."
            ), "ai_score": True},
            {"key": "mistake_lesson", "text": "SMMda qilgan eng katta xatoyingiz nima edi va undan qanday xulosa chiqardingiz?", "ai_score": True},
            {"key": "trend_reaction", "text": (
                "Ijtimoiy tarmoqlarda tez o'zgaruvchi trendlarga qanday moslashasiz? "
                "Oxirgi kuzatgan va ishlatgan trendingizni ayting."
            ), "ai_score": True},
            {"key": "crisis_management", "text": (
                "Agar brend haqida salbiy komment yoki kichik inqiroziy vaziyat yuzaga kelsa, "
                "birinchi qadamingiz nima bo'ladi?"
            ), "ai_score": True},
            {"key": "tools", "text": "Qanday dizayn/analitika vositalaridan (Canva, Meta Business Suite va h.k.) foydalanasiz?"},
            {"key": "salary_expectation", "text": "Kutayotgan oylik maoshingiz qancha? (taxminiy raqamda yozing)"},
        ],
    },
]


async def _migrate_to_multi_tenant(db) -> None:
    """Eski (bir-mijozli) jonli bazani ko'p-mijozli sxemaga XAVFSIZ ko'chiradi.

    Faqat BIR MARTA ishlaydi (`applications`da `tenant_id` ustuni yo'q bo'lsagina
    ishga tushadi) va MAVJUD HAQIQIY MA'LUMOTNI (arizalar, vakansiyalar,
    sozlamalar) yo'qotmasdan, ularni "asoschi" nomli birinchi tenant'ga
    biriktiradi — shunda jonli bot xuddi avvalgidek ishlashda davom etadi,
    faqat endi "ko'p mijozli tizimning bitta mijozi" sifatida.
    """
    from config import ADMIN_BOT_TOKEN, ADMIN_USER_IDS, BOT_TOKEN

    cursor = await db.execute("PRAGMA table_info(applications)")
    app_columns = {row[1] for row in await cursor.fetchall()}
    if "tenant_id" in app_columns:
        return  # Allaqachon ko'chirilgan — hech narsa qilmaymiz.

    if not BOT_TOKEN:
        logger.warning("BOT_TOKEN sozlanmagan — ko'p-mijozli migratsiya o'tkazib yuborildi.")
        return

    logger.info("=== Bir-mijozli bazadan ko'p-mijozli sxemaga migratsiya boshlandi ===")

    cursor = await db.execute("SELECT id FROM tenants WHERE bot_token = ?", (BOT_TOKEN,))
    row = await cursor.fetchone()
    if row:
        founder_id = row[0]
    else:
        created_at = datetime.now(timezone.utc).isoformat()
        cursor = await db.execute(
            "INSERT INTO tenants (company_name, bot_token, admin_bot_token, admin_user_ids, "
            "status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
            ("Asosiy kompaniya", BOT_TOKEN, ADMIN_BOT_TOKEN or "",
             json.dumps(list(ADMIN_USER_IDS)), created_at),
        )
        founder_id = cursor.lastrowid
    logger.info("Asoschi mijoz (tenant_id=%s) tayyor.", founder_id)

    # --- applications: ustun qo'shish yetarli (PRIMARY KEY o'zgarmagan) ---
    await db.execute("ALTER TABLE applications ADD COLUMN tenant_id INTEGER")
    await db.execute("UPDATE applications SET tenant_id = ? WHERE tenant_id IS NULL", (founder_id,))
    logger.info("Migratsiya: applications -> tenant_id qo'shildi va to'ldirildi.")

    # --- vacancies: PRIMARY KEY o'zgargani uchun jadval to'liq qayta quriladi ---
    await db.execute("ALTER TABLE vacancies RENAME TO vacancies_old")
    await db.execute(_CREATE_VACANCIES_TABLE_SQL)
    await db.execute(
        """
        INSERT INTO vacancies (tenant_id, key, title, title_ru, reject_message,
            reject_message_ru, questions, questions_ru, resume_required, active, created_at)
        SELECT ?, key, title, title_ru, reject_message, reject_message_ru, questions,
            questions_ru, resume_required, active, created_at
        FROM vacancies_old
        """,
        (founder_id,),
    )
    await db.execute("DROP TABLE vacancies_old")
    logger.info("Migratsiya: vacancies qayta qurildi (mavjud vakansiyalar saqlab qolindi).")

    # --- interview_slots: ustun qo'shish yetarli ---
    await db.execute("ALTER TABLE interview_slots ADD COLUMN tenant_id INTEGER")
    await db.execute("UPDATE interview_slots SET tenant_id = ? WHERE tenant_id IS NULL", (founder_id,))
    logger.info("Migratsiya: interview_slots -> tenant_id qo'shildi.")

    # --- interview_settings: PRIMARY KEY o'zgargani uchun qayta quriladi ---
    await db.execute("ALTER TABLE interview_settings RENAME TO interview_settings_old")
    await db.execute(_CREATE_INTERVIEW_SETTINGS_TABLE_SQL)
    await db.execute(
        """
        INSERT INTO interview_settings (tenant_id, location_text, location_lat, location_lng,
            interviewer_name, interviewer_phone, notes)
        SELECT ?, location_text, location_lat, location_lng, interviewer_name,
            interviewer_phone, notes
        FROM interview_settings_old WHERE id = 1
        """,
        (founder_id,),
    )
    await db.execute("DROP TABLE interview_settings_old")
    logger.info("Migratsiya: interview_settings qayta qurildi.")

    logger.info("=== Migratsiya muvaffaqiyatli yakunlandi (asoschi tenant_id=%s) ===", founder_id)


async def _ensure_founder_tenant(db) -> None:
    """BOT_TOKEN'ga mos tenant yozuvi mavjudligini ta'minlaydi — bu ham
    yangi (bo'sh) baza, ham allaqachon migratsiya qilingan baza uchun
    ishlaydi (`_migrate_to_multi_tenant` faqat ESKI sxemani aniqlaganda
    ishga tushadi, shuning uchun bu alohida, har doim tekshiriladigan
    qadam sifatida kerak)."""
    from config import ADMIN_BOT_TOKEN, ADMIN_USER_IDS, BOT_TOKEN

    if not BOT_TOKEN:
        return

    cursor = await db.execute("SELECT id FROM tenants WHERE bot_token = ?", (BOT_TOKEN,))
    if await cursor.fetchone():
        return  # Allaqachon bor (migratsiya orqali yoki avvalgi ishga tushirishda).

    created_at = datetime.now(timezone.utc).isoformat()
    cursor = await db.execute(
        "INSERT INTO tenants (company_name, bot_token, admin_bot_token, admin_user_ids, "
        "status, created_at) VALUES (?, ?, ?, ?, 'active', ?)",
        ("Asosiy kompaniya", BOT_TOKEN, ADMIN_BOT_TOKEN or "",
         json.dumps(list(ADMIN_USER_IDS)), created_at),
    )
    founder_id = cursor.lastrowid

    for v in _DEFAULT_VACANCIES:
        await db.execute(
            "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "
            "resume_required, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (founder_id, v["key"], v["title"], v["reject_message"],
             json.dumps(v["questions"], ensure_ascii=False), int(v["resume_required"]), created_at),
        )
    logger.info("Yangi (bo'sh) baza uchun asoschi tenant yaratildi (id=%s), standart vakansiyalar urug'landi.", founder_id)


async def init_db():
    """Jadval strukturasini yaratadi, (agar kerak bo'lsa) eski bir-mijozli
    jonli bazani ko'p-mijozli sxemaga xavfsiz ko'chiradi, VA har doim
    BOT_TOKEN'ga mos "asoschi" tenant mavjudligini ta'minlaydi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(_CREATE_TENANTS_TABLE_SQL)
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_CREATE_VACANCIES_TABLE_SQL)
        await db.execute(_CREATE_INTERVIEW_SLOTS_TABLE_SQL)
        await db.execute(_CREATE_INTERVIEW_SETTINGS_TABLE_SQL)
        await db.execute(_CREATE_PAYMENT_ORDERS_TABLE_SQL)
        await db.execute(_CREATE_SALES_LEADS_TABLE_SQL)

        cursor = await db.execute("PRAGMA table_info(tenants)")
        tenant_columns = {row[1] for row in await cursor.fetchall()}
        if "contact_phone" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN contact_phone TEXT")
        if "contact_full_name" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN contact_full_name TEXT")
        if "plan" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN plan TEXT")
        if "plan_applications_limit" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN plan_applications_limit INTEGER")
        if "plan_vacancy_limit" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN plan_vacancy_limit INTEGER")
        if "plan_expires_at" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN plan_expires_at TEXT")
        if "period_started_at" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN period_started_at TEXT")
        if "applications_ever_count" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN applications_ever_count INTEGER NOT NULL DEFAULT 0")
            # Backfill: mavjud tenantlar uchun hozirgi (hali o'chirilmagan) arizalar
            # sonini boshlang'ich qiymat sifatida olamiz — aks holda ular
            # noto'g'ri ravishda "0" dan boshlangan bo'lib qolardi.
            await db.execute(
                "UPDATE tenants SET applications_ever_count = "
                "(SELECT COUNT(*) FROM applications WHERE applications.tenant_id = tenants.id)"
            )
        if "applications_used_in_period" not in tenant_columns:
            await db.execute("ALTER TABLE tenants ADD COLUMN applications_used_in_period INTEGER NOT NULL DEFAULT 0")

        cursor = await db.execute("PRAGMA table_info(payment_orders)")
        payment_columns = {row[1] for row in await cursor.fetchall()}
        if "plan" not in payment_columns:
            await db.execute("ALTER TABLE payment_orders ADD COLUMN plan TEXT")

        cursor = await db.execute("PRAGMA table_info(payment_orders)")
        po_columns = {row[1] for row in await cursor.fetchall()}
        if "notify_bot_token" not in po_columns:
            await db.execute("ALTER TABLE payment_orders ADD COLUMN notify_bot_token TEXT")
        if "notify_chat_id" not in po_columns:
            await db.execute("ALTER TABLE payment_orders ADD COLUMN notify_chat_id INTEGER")
        await db.execute(_CREATE_PAYMENT_NOTIFICATIONS_TABLE_SQL)
        await db.execute(_CREATE_BOT_STARTS_TABLE_SQL)
        await db.commit()

        await _migrate_to_multi_tenant(db)
        await _ensure_founder_tenant(db)
        await db.commit()
    logger.info("Ma'lumotlar bazasi (ko'p mijozli) tayyor: %s", SQLITE_PATH)


# ============================= MIJOZLAR (tenants) =============================

# ============================= SOTUV LIDLARI (sales_leads) =============================
# /create_bot oqimida (services/sales_conversation.py + handlers/create_bot.py)
# kompaniya nomi kiritilgan zahoti yaratiladi — hali ikkita bot toke ni
# tasdiqlanmagan bo'lsa ham. Asoschi buni push-xabar sifatida emas, Admin
# panelidagi "🎯 Lidlar" bo'limini ochganda ko'radi.

async def create_lead(
    telegram_user_id: int, telegram_username: str, phone: str, full_name: str,
    company_name: str, conversation_summary: str,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO sales_leads (telegram_user_id, telegram_username, phone, "
            "full_name, company_name, conversation_summary, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'yangi', ?)",
            (telegram_user_id, telegram_username, phone, full_name, company_name,
             conversation_summary, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def mark_lead_converted(lead_id: int, tenant_id: int) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE sales_leads SET status = 'mijozga aylandi', tenant_id = ? WHERE id = ?",
            (tenant_id, lead_id),
        )
        await db.commit()


async def count_leads() -> int:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM sales_leads")
        row = await cursor.fetchone()
        return row[0] if row else 0


async def list_leads(limit: int = 10, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sales_leads ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def create_tenant(
    company_name: str, bot_token: str, admin_bot_token: str, admin_user_ids: list[int],
    contact_phone: str = "", contact_full_name: str = "",
) -> int:
    """Yangi mijoz yaratadi va unga standart 3 ta namunaviy vakansiyani urug'laydi.
    Ikkita alohida token oladi: `bot_token` — nomzod-bot uchun, `admin_bot_token` —
    faqat shu mijozning administratorlari ishlatadigan Admin panel-bot uchun.
    `contact_phone`/`contact_full_name` — sotuv suhbatida yig'ilgan lid ma'lumoti
    (CRM/follow-up uchun)."""
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tenants (company_name, bot_token, admin_bot_token, admin_user_ids, "
            "contact_phone, contact_full_name, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (company_name, bot_token, admin_bot_token, json.dumps(admin_user_ids),
             contact_phone, contact_full_name, created_at),
        )
        tenant_id = cursor.lastrowid

        for v in _DEFAULT_VACANCIES:
            await db.execute(
                "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "
                "resume_required, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
                (tenant_id, v["key"], v["title"], v["reject_message"],
                 json.dumps(v["questions"], ensure_ascii=False), int(v["resume_required"]), created_at),
            )
        await db.commit()
    logger.info("Yangi mijoz yaratildi: id=%s, %s", tenant_id, company_name)
    return tenant_id


async def get_tenant(tenant_id: int) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,))
        row = await cursor.fetchone()
    if not row:
        return None
    t = dict(row)
    t["admin_user_ids"] = json.loads(t["admin_user_ids"])
    return t


async def get_tenant_by_role_token(token: str) -> Optional[tuple[dict, str]]:
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

        cursor = await db.execute("SELECT * FROM tenants WHERE admin_bot_token = ?", (token,))
        row = await cursor.fetchone()
        if row:
            t = dict(row)
            t["admin_user_ids"] = json.loads(t["admin_user_ids"])
            return t, "admin"

    return None


async def get_tenant_by_token(bot_token: str) -> Optional[dict]:
    """ESKIRGAN: `get_tenant_by_role_token`ni ishlating. Faqat orqaga moslik
    uchun (masalan `/create_bot`da "bu token allaqachon band" tekshiruvi
    ikkala ustunni ham qamrab olishi kerak — shu funksiya endi ikkalasini
    ham tekshiradi)."""
    result = await get_tenant_by_role_token(bot_token)
    return result[0] if result else None


async def list_tenants(status: Optional[str] = None, statuses: Optional[list[str]] = None) -> list[dict]:
    """`status` — bitta holat (eski, orqaga moslik uchun). `statuses` — bir
    nechta holatni (masalan ["active", "trial", "trial_expired"]) bir yo'la
    so'rash uchun."""
    query = "SELECT * FROM tenants"
    params: tuple = ()
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        query += f" WHERE status IN ({placeholders})"
        params = tuple(statuses)
    elif status:
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
        result.append(t)
    return result


async def update_tenant_status(tenant_id: int, status: str, bot_username: Optional[str] = None) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        if bot_username is not None:
            await db.execute(
                "UPDATE tenants SET status = ?, bot_username = ? WHERE id = ?",
                (status, bot_username, tenant_id),
            )
        else:
            await db.execute("UPDATE tenants SET status = ? WHERE id = ?", (status, tenant_id))
        await db.commit()


async def set_admin_bot_username(tenant_id: int, username: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute("UPDATE tenants SET admin_bot_username = ? WHERE id = ?", (username, tenant_id))
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
    *, tenant_id: int, user_id: int, username: str, full_name: str,
    vacancy_key: str, vacancy_title: str, answers: dict, ai_scores: dict,
    resume_file_id: Optional[str], video_file_id: Optional[str], status: str,
    phone_number: str = "", lang: str = "uz",
    ai_suspect_flags: Optional[list] = None, voice_answers: Optional[dict] = None,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO applications (
                tenant_id, user_id, username, full_name, vacancy_key, vacancy_title,
                answers, ai_scores, resume_file_id, video_file_id, status,
                phone_number, lang, ai_suspect_flags, voice_answers, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, user_id, username, full_name, vacancy_key, vacancy_title,
             json.dumps(answers, ensure_ascii=False), json.dumps(ai_scores, ensure_ascii=False),
             resume_file_id, video_file_id, status, phone_number, lang,
             json.dumps(ai_suspect_flags or [], ensure_ascii=False),
             json.dumps(voice_answers or {}, ensure_ascii=False), created_at),
        )
        await db.execute(
            "UPDATE tenants SET applications_ever_count = applications_ever_count + 1, "
            "applications_used_in_period = applications_used_in_period + 1 WHERE id = ?",
            (tenant_id,),
        )
        await db.commit()
        return cursor.lastrowid


async def get_application(tenant_id: int, app_id: int) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE id = ? AND tenant_id = ?", (app_id, tenant_id),
        )
        row = await cursor.fetchone()
    return _parse_app_row(row) if row else None


async def get_pending_application_for_user(tenant_id: int, user_id: int) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE tenant_id = ? AND user_id = ? AND status = 'pending' "
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
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET status = ? WHERE id = ? AND tenant_id = ?",
            (status, app_id, tenant_id),
        )
        await db.commit()


async def try_book_slot(tenant_id: int, app_id: int, slot: str, capacity: int) -> bool:
    """Atomik band qilish — bitta SQL ichida joy borligini tekshirib yozadi
    (race condition oldini olish uchun), FAQAT shu mijoz doirasida."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE applications
            SET selected_slot = ?
            WHERE id = ? AND tenant_id = ?
              AND (SELECT COUNT(*) FROM applications WHERE selected_slot = ? AND tenant_id = ?) < ?
            """,
            (slot, app_id, tenant_id, slot, tenant_id, capacity),
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


async def get_applications_for_vacancy(tenant_id: int, vacancy_key: str, limit: int = 300) -> list[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE tenant_id = ? AND vacancy_key = ? ORDER BY id DESC LIMIT ?",
            (tenant_id, vacancy_key, limit),
        )
        rows = await cursor.fetchall()
    return [_parse_app_row(r) for r in rows]


# ============================= VAKANSIYALAR (admin bot) =============================

def _row_to_vacancy(row) -> dict:
    v = dict(row)
    v["questions"] = json.loads(v["questions"])
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


async def _get_localized_title(tenant_id: int, key: str, title_uz: str, lang: str) -> str:
    if lang != "ru":
        return title_uz

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT title_ru FROM vacancies WHERE tenant_id = ? AND key = ?", (tenant_id, key),
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


async def list_vacancies_localized(tenant_id: int, lang: str, active_only: bool = True) -> list[dict]:
    vacancies = await list_vacancies(tenant_id, active_only=active_only)
    if lang != "ru":
        return vacancies
    result = []
    for v in vacancies:
        v = dict(v)
        v["title"] = await _get_localized_title(tenant_id, v["key"], v["title"], lang)
        result.append(v)
    return result


async def get_vacancy(tenant_id: int, key: str) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM vacancies WHERE tenant_id = ? AND key = ?", (tenant_id, key),
        )
        row = await cursor.fetchone()
    return _row_to_vacancy(row) if row else None


async def get_vacancy_localized(tenant_id: int, key: str, lang: str) -> Optional[dict]:
    vacancy = await get_vacancy(tenant_id, key)
    if not vacancy or lang != "ru":
        return vacancy

    vacancy = dict(vacancy)
    vacancy["title"] = await _get_localized_title(tenant_id, key, vacancy["title"], lang)

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT questions_ru, reject_message_ru FROM vacancies WHERE tenant_id = ? AND key = ?",
            (tenant_id, key),
        )
        row = await cursor.fetchone()

    if row and row["questions_ru"]:
        vacancy["questions"] = json.loads(row["questions_ru"])
        vacancy["reject_message"] = row["reject_message_ru"] or vacancy["reject_message"]
        return vacancy

    from services.ai_scoring import translate_vacancy_content
    translated = await translate_vacancy_content(vacancy["questions"], vacancy["reject_message"])
    if not translated:
        logger.warning("Vakansiya (tenant=%s, %s) rus tiliga tarjima qilinmadi.", tenant_id, key)
        return vacancy

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE vacancies SET questions_ru = ?, reject_message_ru = ? WHERE tenant_id = ? AND key = ?",
            (json.dumps(translated["questions"], ensure_ascii=False), translated["reject_message"],
             tenant_id, key),
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
    *, tenant_id: int, key: str, title: str, reject_message: str, questions: list, resume_required: bool
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "INSERT INTO vacancies (tenant_id, key, title, reject_message, questions, "
            "resume_required, active, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            (tenant_id, key, title, reject_message, json.dumps(questions, ensure_ascii=False),
             int(resume_required), created_at),
        )
        await db.commit()


async def update_vacancy(tenant_id: int, key: str, **fields) -> None:
    if not fields:
        return
    set_clauses, values = [], []
    for field, value in fields.items():
        if field == "questions":
            value = json.dumps(value, ensure_ascii=False)
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
            f"UPDATE vacancies SET {', '.join(set_clauses)} WHERE tenant_id = ? AND key = ?", values,
        )
        await db.commit()


async def delete_applications_for_vacancy(tenant_id: int, vacancy_key: str) -> int:
    """Shu vakansiyaga tegishli BARCHA arizalarni o'chiradi (vakansiyaning
    o'zi qoladi). Statistikadan ham chiqib ketadi. Alohida "qayta topshirishga
    ruxsat" berish shart emas — takroriy ariza himoyasi faqat "hozir kutilayotgan
    arizasi bormi" tekshiruviga asoslangan (handlers/start.py), vakansiyaga xos
    emas — shuning uchun o'chirilgach, o'sha nomzodlar avtomatik qayta
    topshira oladi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM applications WHERE tenant_id = ? AND vacancy_key = ?",
            (tenant_id, vacancy_key),
        )
        await db.commit()
        return cursor.rowcount


async def delete_vacancy(tenant_id: int, key: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute("DELETE FROM vacancies WHERE tenant_id = ? AND key = ?", (tenant_id, key))
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


async def add_interview_slot(tenant_id: int, label: str, capacity: int = 1) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO interview_slots (tenant_id, label, capacity, active, created_at) VALUES (?, ?, ?, 1, ?)",
            (tenant_id, label, capacity, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_interview_slot(tenant_id: int, slot_id: int):
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "DELETE FROM interview_slots WHERE id = ? AND tenant_id = ?", (slot_id, tenant_id),
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
        cursor = await db.execute("SELECT * FROM interview_settings WHERE tenant_id = ?", (tenant_id,))
        row = await cursor.fetchone()
    if not row:
        return {
            "location_text": None, "location_lat": None, "location_lng": None,
            "interviewer_name": None, "interviewer_phone": None, "notes": None,
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
            (tenant_id, merged.get("location_text"), merged.get("location_lat"), merged.get("location_lng"),
             merged.get("interviewer_name"), merged.get("interviewer_phone"), merged.get("notes")),
        )
        await db.commit()


# ============================= STATISTIKA (admin bot) =============================

_TERMINAL_REJECTED_STATUSES = {
    "rejected_hard_filter", "rejected_irrelevant", "rejected_ai_generated", "declined",
}


async def record_bot_start(tenant_id: int, user_id: int) -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "INSERT INTO bot_starts (tenant_id, user_id, started_at) VALUES (?, ?, ?)",
            (tenant_id, user_id, started_at),
        )
        await db.commit()


async def count_tenant_applications(tenant_id: int) -> int:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM applications WHERE tenant_id = ?", (tenant_id,))
        row = await cursor.fetchone()
    return row[0] if row else 0


async def set_tenant_plan(tenant_id: int, plan_key: str) -> None:
    """To'lov tasdiqlangach chaqiriladi — tarifni faollashtiradi, davrni
    (ariza/vakansiya limiti, muddat) HOZIRDAN boshlab hisoblaydi."""
    from services.plans import PLANS

    plan = PLANS[plan_key]
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(days=plan["days"])).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE tenants SET plan = ?, plan_applications_limit = ?, plan_vacancy_limit = ?, "
            "plan_expires_at = ?, period_started_at = ?, applications_used_in_period = 0, "
            "status = 'active' WHERE id = ?",
            (plan_key, plan["applications"], plan["vacancies"], expires_at, now.isoformat(), tenant_id),
        )
        await db.commit()


async def get_time_based_stats(tenant_id: int) -> dict:
    """Bugun/bu hafta/bu oy nechta ariza tushganini hisoblaydi — asoschiga
    faoliyat tendensiyasini (o'sish/pasayish) ko'rsatish uchun."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT created_at FROM applications WHERE tenant_id = ?", (tenant_id,)
        )
        rows = await cursor.fetchall()

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)

    today = week = month = 0
    for (created_at,) in rows:
        try:
            dt = datetime.fromisoformat(created_at)
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt >= today_start:
            today += 1
        if dt >= week_start:
            week += 1
        if dt >= month_start:
            month += 1
    return {"today": today, "week": week, "month": month}


async def get_ai_verdict_stats(tenant_id: int) -> dict:
    """Barcha arizalar bo'yicha AI verdikt (🟢/🟡/🔴) taqsimoti va o'rtacha
    ball — nomzodlar sifatini bir qarashda ko'rsatish uchun."""
    from services.ai_scoring import aggregate_scores

    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT ai_scores FROM applications WHERE tenant_id = ?", (tenant_id,)
        )
        rows = await cursor.fetchall()

    verdict_counts = {"yashil": 0, "sariq": 0, "qizil": 0}
    scores = []
    for (ai_scores_json,) in rows:
        try:
            ai_scores = json.loads(ai_scores_json) if ai_scores_json else {}
        except (TypeError, ValueError):
            continue
        aggregate = aggregate_scores(ai_scores)
        if aggregate:
            verdict_counts[aggregate["verdict"]] = verdict_counts.get(aggregate["verdict"], 0) + 1
            scores.append(aggregate["avg_score"])

    avg_score = round(sum(scores) / len(scores)) if scores else None
    return {"verdict_counts": verdict_counts, "avg_score": avg_score, "scored_total": len(scores)}


async def get_overall_stats(tenant_id: int) -> dict:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM applications WHERE tenant_id = ? GROUP BY status", (tenant_id,),
        )
        rows = await cursor.fetchall()

        cursor = await db.execute(
            "SELECT COUNT(*), COUNT(DISTINCT user_id) FROM bot_starts WHERE tenant_id = ?", (tenant_id,),
        )
        starts_total, starts_unique = await cursor.fetchone()

    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    rejected_total = sum(by_status.get(s, 0) for s in _TERMINAL_REJECTED_STATUSES)

    conversion_percent = round(100 * total / starts_unique) if starts_unique else None

    return {
        "total": total, "pending": by_status.get("pending", 0), "accepted": by_status.get("accepted", 0),
        "declined_by_admin": by_status.get("declined", 0),
        "rejected_hard_filter": by_status.get("rejected_hard_filter", 0),
        "rejected_irrelevant": by_status.get("rejected_irrelevant", 0),
        "rejected_ai_generated": by_status.get("rejected_ai_generated", 0),
        "rejected_total": rejected_total, "by_status": by_status,
        "starts_total": starts_total or 0, "starts_unique": starts_unique or 0,
        "conversion_percent": conversion_percent,
    }


async def get_vacancy_stats(tenant_id: int) -> list[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT vacancy_key, vacancy_title, status, COUNT(*) FROM applications "
            "WHERE tenant_id = ? GROUP BY vacancy_key, vacancy_title, status", (tenant_id,),
        )
        rows = await cursor.fetchall()

    per_vacancy: dict[str, dict] = {}
    for vacancy_key, vacancy_title, status, count in rows:
        entry = per_vacancy.setdefault(
            vacancy_key,
            {"vacancy_key": vacancy_key, "vacancy_title": vacancy_title, "total": 0,
             "pending": 0, "accepted": 0, "rejected": 0},
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
    tenant_id: int, order_code: str, base_amount: int, amount: int, expires_at: str,
    notify_bot_token: str = None, notify_chat_id: int = None, plan: str = None,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO payment_orders (tenant_id, order_code, base_amount, amount, "
            "status, created_at, expires_at, notify_bot_token, notify_chat_id, plan) "
            "VALUES (?, ?, ?, ?, 'awaiting_payment', ?, ?, ?, ?, ?)",
            (tenant_id, order_code, base_amount, amount, created_at, expires_at,
             notify_bot_token, notify_chat_id, plan),
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


async def get_open_payment_order_by_amount(amount: int) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'awaiting_payment' AND amount = ? LIMIT 1",
            (amount,),
        )
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_open_payment_orders_by_amount(amount: int) -> list[dict]:
    """Muddati o'tmagan, aynan shu summali ochiq buyurtmalarni qaytaradi."""
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM payment_orders WHERE status = 'awaiting_payment' "
            "AND amount = ? AND expires_at > ?",
            (amount, now),
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


async def mark_payment_order_needs_review(order_id: int, notification_text: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE payment_orders SET status = 'needs_review', notification_text = ? WHERE id = ?",
            (notification_text, order_id),
        )
        await db.commit()


async def was_notification_seen_recently(text_hash: str, minutes: int = 30) -> bool:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT received_at FROM payment_notifications_seen WHERE hash = ?", (text_hash,),
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
