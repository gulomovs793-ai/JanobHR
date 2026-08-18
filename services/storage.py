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
from typing import Any, Dict, Optional

import aiosqlite
from aiogram.fsm.storage.base import BaseStorage, StorageKey

logger = logging.getLogger("janob_hr_bot")

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fsm_storage (
    storage_key TEXT PRIMARY KEY,
    state TEXT,
    data TEXT NOT NULL DEFAULT '{}'
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
            await db.commit()
        logger.info("FSM storage (SQLite) tayyor.")

    async def set_state(self, key: StorageKey, state=None) -> None:
        state_str = state.state if hasattr(state, "state") else state
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO fsm_storage (storage_key, state, data) VALUES (?, ?, '{}')
                ON CONFLICT(storage_key) DO UPDATE SET state = excluded.state
                """,
                (_key_str(key), state_str),
            )
            await db.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute(
                "SELECT state FROM fsm_storage WHERE storage_key = ?", (_key_str(key),)
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        data_json = json.dumps(data, ensure_ascii=False)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO fsm_storage (storage_key, state, data) VALUES (?, NULL, ?)
                ON CONFLICT(storage_key) DO UPDATE SET data = excluded.data
                """,
                (_key_str(key), data_json),
            )
            await db.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
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
