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


async def init_db():
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(_CREATE_TABLE_SQL)
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
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(SQLITE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO applications (
                user_id, username, full_name, vacancy_key, vacancy_title,
                answers, ai_scores, resume_file_id, video_file_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    return app


async def set_admin_message(app_id: int, message_id: int):
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET admin_message_id = ? WHERE id = ?",
            (message_id, app_id),
        )
        await db.commit()


async def update_status(app_id: int, status: str):
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, app_id),
        )
        await db.commit()
