"""
Janob HR Bot — SQLite orqali FSM holatini saqlovchi doimiy (persistent) storage.

aiogram'ning standart MemoryStorage'i butun suhbat holatini (nomzod qaysi savolda
turgani, oldingi javoblari va h.k.) faqat operativ xotirada saqlaydi. Bot qayta
ishga tushganda (deploy, qayta ishga tushirish) bu holat BUTUNLAY yo'qoladi —
natijada, aynan o'sha payt anketa to'ldirayotgan nomzod uchun bot "jim qolib",
uning xabariga umuman javob bermay qo'yadi.

Bu klass xuddi shu ma'lumotni SQLite'da saqlaydi, shuning uchun jarayon qayta
ishga tushsa ham (fayl tizimi saqlanib qolgan bo'lsa — buning uchun Render'da
Disk ulash tavsiya etiladi), nomzodlar hech narsani sezmasdan davom eta oladi.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiosqlite
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from config import SQLITE_PATH

logger = logging.getLogger("janob_hr_bot")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fsm_storage (
    storage_key TEXT PRIMARY KEY,
    state TEXT,
    data TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT,
    reminder_stage TEXT
);
"""


def _key_str(key: StorageKey) -> str:
    parts = [str(key.bot_id), str(key.chat_id), str(key.user_id)]
    if key.thread_id is not None:
        parts.append(f"t{key.thread_id}")
    if key.destiny and key.destiny != "default":
        parts.append(str(key.destiny))
    return ":".join(parts)


class SQLiteStorage(BaseStorage):
    """aiogram uchun SQLite'ga asoslangan doimiy FSM storage."""

    def __init__(self, db_path: str):
        self._db_path = db_path

    async def init(self):
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(_CREATE_TABLE_SQL)
            cursor = await db.execute("PRAGMA table_info(fsm_storage)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "updated_at" not in columns:
                await db.execute("ALTER TABLE fsm_storage ADD COLUMN updated_at TEXT")
            if "reminder_stage" not in columns:
                await db.execute("ALTER TABLE fsm_storage ADD COLUMN reminder_stage TEXT")
            await db.execute(
                "UPDATE fsm_storage SET updated_at=COALESCE(updated_at, ?) WHERE state IS NOT NULL",
                (datetime.now(timezone.utc).isoformat(),),
            )
            await db.commit()
        logger.info("FSM storage (SQLite) tayyor.")

    async def set_state(self, key: StorageKey, state=None) -> None:
        state_str = state.state if hasattr(state, "state") else state
        async with aiosqlite.connect(self._db_path) as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                """
                INSERT INTO fsm_storage (storage_key, state, data, updated_at, reminder_stage)
                VALUES (?, ?, '{}', ?, NULL)
                ON CONFLICT(storage_key) DO UPDATE SET
                    state = excluded.state, updated_at = excluded.updated_at, reminder_stage = NULL
                """,
                (_key_str(key), state_str, now),
            )
            await db.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT state FROM fsm_storage WHERE storage_key = ?", (_key_str(key),)
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: dict[str, Any]) -> None:
        data_json = json.dumps(data, ensure_ascii=False)
        async with aiosqlite.connect(self._db_path) as db:
            now = datetime.now(timezone.utc).isoformat()
            await db.execute(
                """
                INSERT INTO fsm_storage (storage_key, state, data, updated_at, reminder_stage)
                VALUES (?, NULL, ?, ?, NULL)
                ON CONFLICT(storage_key) DO UPDATE SET
                    data = excluded.data, updated_at = excluded.updated_at, reminder_stage = NULL
                """,
                (_key_str(key), data_json, now),
            )
            await db.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT data FROM fsm_storage WHERE storage_key = ?", (_key_str(key),)
            )
            row = await cursor.fetchone()
        if not row or not row[0]:
            return {}
        try:
            return json.loads(row[0])
        except Exception:
            logger.exception("FSM data'ni o'qib bo'lmadi (key=%s).", _key_str(key))
            return {}

    async def close(self) -> None:
        pass


async def list_stale_candidate_sessions(minutes: int = 30) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    try:
        async with aiosqlite.connect(SQLITE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT storage_key, state, data, updated_at, reminder_stage FROM fsm_storage "
                "WHERE state IS NOT NULL AND updated_at IS NOT NULL AND updated_at<=? "
                "ORDER BY updated_at LIMIT 100",
                (cutoff,),
            )
            rows = await cursor.fetchall()
    except aiosqlite.OperationalError:
        return []
    now = datetime.now(timezone.utc)
    result = []
    for row in rows:
        try:
            data = json.loads(row["data"] or "{}")
            tenant_id = int(data.get("tenant_id"))
            parts = row["storage_key"].split(":")
            chat_id = int(parts[1])
            updated = datetime.fromisoformat(row["updated_at"])
        except (TypeError, ValueError, KeyError, json.JSONDecodeError):
            continue
        age_hours = (now - updated).total_seconds() / 3600
        last = row["reminder_stage"]
        if age_hours >= 24 and last != "24h":
            stage = "24h"
        elif age_hours >= 0.5 and not last:
            stage = "30m"
        else:
            continue
        result.append({
            "storage_key": row["storage_key"], "state": row["state"], "data": data,
            "tenant_id": tenant_id, "chat_id": chat_id, "stage": stage,
        })
    return result


async def mark_candidate_session_reminded(storage_key: str, stage: str) -> None:
    async with aiosqlite.connect(SQLITE_PATH) as db:
        await db.execute(
            "UPDATE fsm_storage SET reminder_stage=? WHERE storage_key=?",
            (stage, storage_key),
        )
        await db.commit()
