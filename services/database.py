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
from datetime import datetime, timezone
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
    admin_user_ids TEXT NOT NULL DEFAULT '[]',
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
        await db.commit()
    logger.info("Ma'lumotlar bazasi (ko'p mijozli) tayyor: %s", SQLITE_PATH)


# ============================= MIJOZLAR (tenants) =============================

async def create_tenant(company_name: str, bot_token: str, admin_user_ids: list[int]) -> int:
    """Yangi mijoz yaratadi va unga standart 3 ta namunaviy vakansiyani urug'laydi.
    Boshlang'ich holati "pending" — to'lov tasdiqlangach `activate_tenant` chaqiriladi."""
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO tenants (company_name, bot_token, admin_user_ids, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (company_name, bot_token, json.dumps(admin_user_ids), created_at),
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


async def get_tenant_by_token(bot_token: str) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM tenants WHERE bot_token = ?", (bot_token,))
        row = await cursor.fetchone()
    if not row:
        return None
    t = dict(row)
    t["admin_user_ids"] = json.loads(t["admin_user_ids"])
    return t


async def list_tenants(status: Optional[str] = None) -> list[dict]:
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


async def get_overall_stats(tenant_id: int) -> dict:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT status, COUNT(*) FROM applications WHERE tenant_id = ? GROUP BY status", (tenant_id,),
        )
        rows = await cursor.fetchall()

    by_status = {status: count for status, count in rows}
    total = sum(by_status.values())
    rejected_total = sum(by_status.get(s, 0) for s in _TERMINAL_REJECTED_STATUSES)

    return {
        "total": total, "pending": by_status.get("pending", 0), "accepted": by_status.get("accepted", 0),
        "declined_by_admin": by_status.get("declined", 0),
        "rejected_hard_filter": by_status.get("rejected_hard_filter", 0),
        "rejected_irrelevant": by_status.get("rejected_irrelevant", 0),
        "rejected_ai_generated": by_status.get("rejected_ai_generated", 0),
        "rejected_total": rejected_total, "by_status": by_status,
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
