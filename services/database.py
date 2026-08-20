"""
Janob HR Bot — ma'lumotlar bazasi qatlami (SQLite, aiosqlite).
Har bir anketa (application) bitta qatorda saqlanadi.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from config import SQLITE_PATH

logger = logging.getLogger("janob_hr_bot")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    admin_message_id INTEGER,
    created_at TEXT NOT NULL
);
"""

_CREATE_VACANCIES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS vacancies (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    reject_message TEXT NOT NULL,
    questions TEXT NOT NULL,
    resume_required INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

_CREATE_INTERVIEW_SLOTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS interview_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 1,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
"""

# Suhbat manzili, intervyuchi kontakti va eslatma matni — bitta qatorli
# (id=1) global sozlama jadvali. Barcha vakansiyalar uchun umumiy.
_CREATE_INTERVIEW_SETTINGS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS interview_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    location_text TEXT,
    location_lat REAL,
    location_lng REAL,
    interviewer_name TEXT,
    interviewer_phone TEXT,
    notes TEXT
);
"""

# Birinchi marta ishga tushirilganda (vacancies jadvali bo'sh bo'lsa) standart
# 3 ta namunaviy vakansiya bilan to'ldiramiz — bular oddiy boshlang'ich nuqta,
# admin bot orqali istalganini tahrirlash, o'chirish yoki yangisini qo'shish mumkin.
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
        "key": "designer",
        "title": "🎨 Dizayner",
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
        "key": "smm",
        "title": "📱 SMM mutaxassis",
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
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(_CREATE_TABLE_SQL)
        await db.execute(_CREATE_VACANCIES_TABLE_SQL)
        await db.execute(_CREATE_INTERVIEW_SLOTS_TABLE_SQL)
        await db.execute(_CREATE_INTERVIEW_SETTINGS_TABLE_SQL)

        # Yengil migratsiya: eski (allaqachon mavjud) bazalarga yangi ustunlarni
        # xavfsiz qo'shib boramiz — CREATE TABLE IF NOT EXISTS eski jadvalni
        # o'zgartirmaydi, shuning uchun buni qo'lda qilamiz.
        cursor = await db.execute("PRAGMA table_info(applications)")
        existing_columns = {row[1] for row in await cursor.fetchall()}
        if "selected_slot" not in existing_columns:
            await db.execute("ALTER TABLE applications ADD COLUMN selected_slot TEXT")
            logger.info("Migratsiya: 'selected_slot' ustuni qo'shildi.")
        if "phone_number" not in existing_columns:
            await db.execute("ALTER TABLE applications ADD COLUMN phone_number TEXT")
            logger.info("Migratsiya: 'phone_number' ustuni qo'shildi.")
        if "admin_messages" not in existing_columns:
            await db.execute("ALTER TABLE applications ADD COLUMN admin_messages TEXT NOT NULL DEFAULT '[]'")
            logger.info("Migratsiya: 'admin_messages' ustuni qo'shildi.")

        # Vakansiya savollari/rad etish xabarining rus tiliga tarjima keshi —
        # rus tilida so'ragan BIRINCHI nomzodda AI orqali tarjima qilinadi va
        # shu ustunlarga saqlanadi, keyingi nomzodlar uchun qayta tarjima
        # qilinmaydi.
        cursor = await db.execute("PRAGMA table_info(vacancies)")
        vacancy_columns = {row[1] for row in await cursor.fetchall()}
        if "questions_ru" not in vacancy_columns:
            await db.execute("ALTER TABLE vacancies ADD COLUMN questions_ru TEXT")
            logger.info("Migratsiya: 'questions_ru' ustuni qo'shildi.")
        if "reject_message_ru" not in vacancy_columns:
            await db.execute("ALTER TABLE vacancies ADD COLUMN reject_message_ru TEXT")
            logger.info("Migratsiya: 'reject_message_ru' ustuni qo'shildi.")
        if "title_ru" not in vacancy_columns:
            await db.execute("ALTER TABLE vacancies ADD COLUMN title_ru TEXT")
            logger.info("Migratsiya: 'title_ru' ustuni qo'shildi.")
        if "lang" not in existing_columns:
            await db.execute("ALTER TABLE applications ADD COLUMN lang TEXT NOT NULL DEFAULT 'uz'")
            logger.info("Migratsiya: 'lang' ustuni qo'shildi.")
        if "ai_suspect_flags" not in existing_columns:
            await db.execute("ALTER TABLE applications ADD COLUMN ai_suspect_flags TEXT NOT NULL DEFAULT '[]'")
            logger.info("Migratsiya: 'ai_suspect_flags' ustuni qo'shildi.")

        # Birinchi marta ishga tushirilganda vakansiyalar jadvali bo'sh bo'lsa,
        # standart 3 ta namunaviy vakansiya bilan to'ldiramiz.
        cursor = await db.execute("SELECT COUNT(*) FROM vacancies")
        (vacancy_count,) = await cursor.fetchone()
        if vacancy_count == 0:
            created_at = datetime.now(timezone.utc).isoformat()
            for v in _DEFAULT_VACANCIES:
                await db.execute(
                    """
                    INSERT INTO vacancies (key, title, reject_message, questions, resume_required, active, created_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        v["key"], v["title"], v["reject_message"],
                        json.dumps(v["questions"], ensure_ascii=False),
                        int(v["resume_required"]), created_at,
                    ),
                )
            logger.info("Migratsiya: %d ta standart vakansiya urug'landi.", len(_DEFAULT_VACANCIES))

        await db.commit()
    logger.info("Ma'lumotlar bazasi tayyor: %s", SQLITE_PATH)


async def save_application(
    *,
    user_id: int,
    username: str,
    full_name: str,
    vacancy_key: str,
    vacancy_title: str,
    answers: dict,
    ai_scores: dict,
    resume_file_id: Optional[str],
    video_file_id: Optional[str],
    status: str,
    phone_number: str = "",
    lang: str = "uz",
    ai_suspect_flags: Optional[list] = None,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO applications (
                user_id, username, full_name, vacancy_key, vacancy_title,
                answers, ai_scores, resume_file_id, video_file_id, status,
                phone_number, lang, ai_suspect_flags, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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
                created_at,
            ),
        )
        await db.commit()
        app_id = cursor.lastrowid

    # Firebase — ixtiyoriy, sozlanmagan yoki xato bo'lsa botni to'xtatmaydi.
    try:
        from services.firebase_sync import push_application

        await push_application(
            app_id,
            {
                "user_id": user_id,
                "username": username,
                "full_name": full_name,
                "vacancy_key": vacancy_key,
                "vacancy_title": vacancy_title,
                "answers": answers,
                "ai_scores": ai_scores,
                "resume_file_id": resume_file_id,
                "video_file_id": video_file_id,
                "status": status,
                "created_at": created_at,
            },
        )
    except Exception:
        logger.exception("Firebase'ga yozib bo'lmadi (ixtiyoriy xususiyat, davom etamiz).")

    return app_id


async def get_application(app_id: int) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM applications WHERE id = ?", (app_id,))
        row = await cursor.fetchone()

    if not row:
        return None

    app = dict(row)
    app["answers"] = json.loads(app["answers"])
    app["ai_scores"] = json.loads(app["ai_scores"])
    app["admin_messages"] = json.loads(app.get("admin_messages") or "[]")
    app["ai_suspect_flags"] = json.loads(app.get("ai_suspect_flags") or "[]")
    return app


async def get_pending_application_for_user(user_id: int) -> Optional[dict]:
    """Foydalanuvchining hozircha ko'rib chiqilayotgan (pending) arizasi bo'lsa, qaytaradi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE user_id = ? AND status = 'pending' "
            "ORDER BY id DESC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()

    if not row:
        return None

    app = dict(row)
    app["answers"] = json.loads(app["answers"])
    app["ai_scores"] = json.loads(app["ai_scores"])
    app["admin_messages"] = json.loads(app.get("admin_messages") or "[]")
    app["ai_suspect_flags"] = json.loads(app.get("ai_suspect_flags") or "[]")
    return app


async def add_admin_message(app_id: int, chat_id: int, message_id: int):
    """Anketa nechta administratorga yuborilgan bo'lsa, har birining xabar ID'sini
    ro'yxatga qo'shadi (keyinchalik shu ID orqali xabarni yangilash uchun)."""
    app = await get_application(app_id)
    messages = app["admin_messages"] if app else []
    messages.append({"chat_id": chat_id, "message_id": message_id})

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET admin_messages = ? WHERE id = ?",
            (json.dumps(messages, ensure_ascii=False), app_id),
        )
        await db.commit()


async def update_status(app_id: int, status: str):
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, app_id),
        )
        await db.commit()


async def try_book_slot(app_id: int, slot: str, capacity: int) -> bool:
    """Vaqt oralig'iga joy bor bo'lsagina, uni band qiladi (atomik amal).

    Bitta SQL buyrug'i ichida hozirgi bandlik sonini tekshirib, shu zahoti
    yozadi — shu bilan ikkita nomzod bir vaqtda bosganda ikkalasi ham
    "muvaffaqiyatli" bo'lib qolish xavfi (race condition) oldini olinadi.
    Muvaffaqiyatli bo'lsa True, joy qolmagan bo'lsa False qaytaradi.
    """
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE applications
            SET selected_slot = ?
            WHERE id = ?
              AND (SELECT COUNT(*) FROM applications WHERE selected_slot = ?) < ?
            """,
            (slot, app_id, slot, capacity),
        )
        await db.commit()
        return cursor.rowcount > 0


async def count_slot_bookings(slot: str) -> int:
    """Berilgan vaqt oraligʻini hozircha nechta nomzod tanlaganini qaytaradi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM applications WHERE selected_slot = ?", (slot,)
        )
        row = await cursor.fetchone()
    return row[0] if row else 0


async def get_applications_for_vacancy(vacancy_key: str, limit: int = 300) -> list[dict]:
    """Berilgan vakansiyaga tushgan barcha arizalarni (eng yangisi birinchi) qaytaradi.
    Reyting (top-nomzodlar) va boshqa admin ko'rinishlari uchun ishlatiladi."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM applications WHERE vacancy_key = ? ORDER BY id DESC LIMIT ?",
            (vacancy_key, limit),
        )
        rows = await cursor.fetchall()

    apps = []
    for row in rows:
        app = dict(row)
        app["answers"] = json.loads(app["answers"])
        app["ai_scores"] = json.loads(app["ai_scores"])
        app["admin_messages"] = json.loads(app.get("admin_messages") or "[]")
        app["ai_suspect_flags"] = json.loads(app.get("ai_suspect_flags") or "[]")
        apps.append(app)
    return apps


# ============================= VAKANSIYALAR (admin bot) =============================

def _row_to_vacancy(row) -> dict:
    v = dict(row)
    v["questions"] = json.loads(v["questions"])
    v["resume_required"] = bool(v["resume_required"])
    v["active"] = bool(v["active"])
    return v


async def list_vacancies(active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM vacancies"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY created_at DESC"
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
    return [_row_to_vacancy(r) for r in rows]


async def _get_localized_title(key: str, title_uz: str, lang: str) -> str:
    """Vakansiya nomini (title) rus tiliga tarjima qilib, `title_ru` ustuniga keshlaydi.
    Bir marta tarjima qilingandan keyin qayta AI so'rovi yuborilmaydi."""
    if lang != "ru":
        return title_uz

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT title_ru FROM vacancies WHERE key = ?", (key,))
        row = await cursor.fetchone()

    if row and row["title_ru"]:
        return row["title_ru"]

    from services.ai_scoring import translate_simple_text

    translated = await translate_simple_text(title_uz)
    if not translated:
        return title_uz

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute("UPDATE vacancies SET title_ru = ? WHERE key = ?", (translated, key))
        await db.commit()

    return translated


async def list_vacancies_localized(lang: str, active_only: bool = True) -> list[dict]:
    """`list_vacancies`ga o'xshaydi, lekin lang="ru" bo'lsa, har bir vakansiya nomini
    rus tiliga tarjima qilingan holda qaytaradi (birinchi safar AI orqali, keyin keshdan)."""
    vacancies = await list_vacancies(active_only=active_only)
    if lang != "ru":
        return vacancies

    result = []
    for v in vacancies:
        v = dict(v)
        v["title"] = await _get_localized_title(v["key"], v["title"], lang)
        result.append(v)
    return result


async def get_vacancy(key: str) -> Optional[dict]:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM vacancies WHERE key = ?", (key,))
        row = await cursor.fetchone()
    return _row_to_vacancy(row) if row else None


async def get_vacancy_localized(key: str, lang: str) -> Optional[dict]:
    """`get_vacancy`ga o'xshaydi, lekin lang="ru" bo'lsa, nomi, savollari va rad etish
    xabarini rus tiliga tarjima qilingan holda qaytaradi.

    Tarjima birinchi so'ralganda AI orqali qilinadi va `title_ru` / `questions_ru` /
    `reject_message_ru` ustunlariga saqlanadi — keyingi rus tilidagi
    nomzodlar uchun bazadan to'g'ridan-to'g'ri o'qiladi (qayta AI so'rovi
    yuborilmaydi). Tarjima muvaffaqiyatsiz bo'lsa, o'zbekcha versiya qaytadi.
    """
    vacancy = await get_vacancy(key)
    if not vacancy or lang != "ru":
        return vacancy

    vacancy = dict(vacancy)
    vacancy["title"] = await _get_localized_title(key, vacancy["title"], lang)

    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT questions_ru, reject_message_ru FROM vacancies WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()

    if row and row["questions_ru"]:
        vacancy["questions"] = json.loads(row["questions_ru"])
        vacancy["reject_message"] = row["reject_message_ru"] or vacancy["reject_message"]
        return vacancy

    from services.ai_scoring import translate_vacancy_content

    translated = await translate_vacancy_content(vacancy["questions"], vacancy["reject_message"])
    if not translated:
        logger.warning("Vakansiya (%s) rus tiliga tarjima qilinmadi, o'zbekcha qoladi.", key)
        return vacancy

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE vacancies SET questions_ru = ?, reject_message_ru = ? WHERE key = ?",
            (
                json.dumps(translated["questions"], ensure_ascii=False),
                translated["reject_message"],
                key,
            ),
        )
        await db.commit()

    vacancy["questions"] = translated["questions"]
    vacancy["reject_message"] = translated["reject_message"]
    return vacancy


def make_vacancy_key(title: str) -> str:
    """Lavozim nomidan ma'lumotlar bazasi uchun lotin-harfli, pastki chiziqli kalit yasaydi."""
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    # Telegram callback_data 64 baytgacha cheklangan (bu kalit "vac:<key>" kabi
    # prefikslar bilan ishlatiladi), shuning uchun xavfsizlik uchun qisqartiramiz.
    slug = slug[:40]
    return slug or "vakansiya"


async def create_vacancy(
    *, key: str, title: str, reject_message: str, questions: list, resume_required: bool
) -> None:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            """
            INSERT INTO vacancies (key, title, reject_message, questions, resume_required, active, created_at)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (key, title, reject_message, json.dumps(questions, ensure_ascii=False), int(resume_required), created_at),
        )
        await db.commit()


async def update_vacancy(key: str, **fields) -> None:
    """fields: title, reject_message, questions (list), resume_required (bool), active (bool)."""
    if not fields:
        return
    set_clauses = []
    values = []
    for field, value in fields.items():
        if field == "questions":
            value = json.dumps(value, ensure_ascii=False)
        elif field in ("resume_required", "active"):
            value = int(value)
        set_clauses.append(f"{field} = ?")
        values.append(value)

    # Savollar yoki rad etish xabari o'zgartirilsa, eski rus tili tarjimasi
    # eskirib qoladi — uni bekor qilamiz, keyingi rus tilidagi nomzodda
    # qayta (yangilangan matn asosida) tarjima qilinadi.
    if "questions" in fields or "reject_message" in fields:
        set_clauses.append("questions_ru = NULL")
        set_clauses.append("reject_message_ru = NULL")
    if "title" in fields:
        set_clauses.append("title_ru = NULL")

    values.append(key)

    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            f"UPDATE vacancies SET {', '.join(set_clauses)} WHERE key = ?", values
        )
        await db.commit()


async def delete_vacancy(key: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute("DELETE FROM vacancies WHERE key = ?", (key,))
        await db.commit()


# ============================= SUHBAT VAQTLARI (admin bot) =============================

async def list_interview_slots(active_only: bool = True) -> list[dict]:
    query = "SELECT * FROM interview_slots"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY id ASC"
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query)
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def add_interview_slot(label: str, capacity: int = 1) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO interview_slots (label, capacity, active, created_at) VALUES (?, ?, 1, ?)",
            (label, capacity, created_at),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_interview_slot(slot_id: int):
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute("DELETE FROM interview_slots WHERE id = ?", (slot_id,))
        await db.commit()


async def get_available_interview_slots() -> list[dict]:
    """Faol va hali joyi bor (band bo'lganlar soni < sig'imi) vaqtlarni qaytaradi.
    Har biri: id, label, capacity, booked."""
    slots = await list_interview_slots(active_only=True)
    result = []
    for slot in slots:
        booked = await count_slot_bookings(slot["label"])
        if booked < slot["capacity"]:
            result.append({**slot, "booked": booked})
    return result


async def get_interview_settings() -> dict:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM interview_settings WHERE id = 1")
        row = await cursor.fetchone()
    if not row:
        return {
            "location_text": None, "location_lat": None, "location_lng": None,
            "interviewer_name": None, "interviewer_phone": None, "notes": None,
        }
    return dict(row)


async def update_interview_settings(**fields):
    if not fields:
        return
    current = await get_interview_settings()
    merged = {**current, **fields}
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            """
            INSERT INTO interview_settings
                (id, location_text, location_lat, location_lng, interviewer_name, interviewer_phone, notes)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                location_text = excluded.location_text,
                location_lat = excluded.location_lat,
                location_lng = excluded.location_lng,
                interviewer_name = excluded.interviewer_name,
                interviewer_phone = excluded.interviewer_phone,
                notes = excluded.notes
            """,
            (
                merged.get("location_text"), merged.get("location_lat"), merged.get("location_lng"),
                merged.get("interviewer_name"), merged.get("interviewer_phone"), merged.get("notes"),
            ),
        )
        await db.commit()


# ============================= STATISTIKA (admin bot) =============================

# Nomzod uchun "yakuniy" hisoblanadigan holatlar (jarayon tugagan).
_TERMINAL_REJECTED_STATUSES = {
    "rejected_hard_filter", "rejected_irrelevant", "rejected_ai_generated", "declined",
}


async def get_overall_stats() -> dict:
    """Umumiy statistika: jami ariza, holat bo'yicha taqsimot."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute("SELECT status, COUNT(*) FROM applications GROUP BY status")
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


async def get_vacancy_stats() -> list[dict]:
    """Har bir vakansiya bo'yicha ariza sonlari (vakansiya o'chirilgan bo'lsa ham,
    tarixiy statistika saqlanib qoladi — vacancy_title'dan foydalanamiz)."""
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            "SELECT vacancy_key, vacancy_title, status, COUNT(*) FROM applications "
            "GROUP BY vacancy_key, vacancy_title, status"
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
