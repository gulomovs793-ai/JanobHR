"""Verified periodic SQLite backups on the persistent disk."""

import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services import database

logger = logging.getLogger("janob_hr_bot")

BACKUP_INTERVAL_SECONDS = max(3600, int(os.getenv("DB_BACKUP_INTERVAL_SECONDS", "86400")))
BACKUP_RETENTION = max(2, int(os.getenv("DB_BACKUP_RETENTION", "7")))
MIN_BACKUP_GAP_SECONDS = max(1800, int(os.getenv("DB_BACKUP_MIN_GAP_SECONDS", "21600")))
_REQUIRED_TABLES = {"tenants", "applications", "vacancies", "payment_orders"}


def _validate_backup(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {result}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = _REQUIRED_TABLES - tables
        if missing:
            raise RuntimeError(f"Backupda jadvallar yetishmaydi: {sorted(missing)}")
        # A real read from the restored copy catches malformed/corrupt schema pages.
        connection.execute("SELECT COUNT(*) FROM tenants").fetchone()
        connection.execute("SELECT COUNT(*) FROM payment_orders").fetchone()
    finally:
        connection.close()


def create_verified_backup() -> Path | None:
    source = Path(database.SQLITE_PATH)
    if not source.exists():
        return None

    backup_dir = source.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(backup_dir.glob("data-*.sqlite3"), key=lambda p: p.stat().st_mtime)
    now_ts = datetime.now(timezone.utc).timestamp()
    if existing and now_ts - existing[-1].stat().st_mtime < MIN_BACKUP_GAP_SECONDS:
        _validate_backup(existing[-1])
        return existing[-1]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    destination = backup_dir / f"data-{stamp}.sqlite3"
    src = sqlite3.connect(source)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    try:
        _validate_backup(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    existing = sorted(backup_dir.glob("data-*.sqlite3"), key=lambda p: p.stat().st_mtime)
    for old in existing[:-BACKUP_RETENTION]:
        old.unlink(missing_ok=True)
    logger.info("SQLite backup yaratildi va restore-read tekshirildi: %s", destination.name)
    return destination


async def run_backups_forever() -> None:
    while True:
        try:
            await asyncio.to_thread(create_verified_backup)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SQLite backup yaratish/tekshirishda xato.")
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
