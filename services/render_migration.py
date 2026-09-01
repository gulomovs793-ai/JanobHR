"""One-time, authenticated Render disk migration helpers.

The migration is deliberately opt-in on both services.  The legacy worker
creates a consistent SQLite backup and sends it, together with an allowlisted
set of runtime settings, directly to the replacement web service over HTTPS.
The receiver validates the database before atomically installing it.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
from aiohttp import web

logger = logging.getLogger("janob_hr_migration")

MIGRATED_ENV_PATH = Path(
    os.getenv("MIGRATED_ENV_PATH", "/data/migrated_env.json")
)
MIGRATION_MARKER_PATH = Path(
    os.getenv("MIGRATION_MARKER_PATH", "/data/.migration_complete.json")
)
MAX_DATABASE_BYTES = 512 * 1024 * 1024

# Only application settings are copied. Render/system variables and migration
# controls are intentionally excluded so the destination keeps its own URL,
# port, disk path, and one-time authorization settings.
ENV_ALLOWLIST = (
    "BOT_TOKEN",
    "ADMIN_GROUP_ID",
    "ADMIN_BOT_TOKEN",
    "ADMIN_USER_IDS",
    "AI_API_KEY",
    "AI_API_BASE",
    "AI_MODEL",
    "AI_API_KEY_2",
    "AI_API_BASE_2",
    "AI_MODEL_2",
    "AI_API_KEY_3",
    "AI_API_BASE_3",
    "AI_MODEL_3",
    "MINI_APP_BASE_URL",
    "SETUP_BOT_TOKEN",
    "FOUNDER_BOT_TOKEN",
    "FOUNDER_USER_ID",
    "PAYMENT_CARD_NUMBER",
    "PAYMENT_CARD_HOLDER",
    "MONTHLY_PRICE_SOM",
    "ORDER_TTL_MINUTES",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_USERBOT_SESSION",
    "CARD_BOT_USERNAME",
    "MAX_ANSWER_CHARS",
    "SELL_SCORE_THRESHOLD",
    "COMPANY_PITCH_TEXT",
    "COMPANY_PITCH_IMAGE_URL",
)


def env_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def collect_runtime_settings() -> dict[str, str]:
    return {
        key: value
        for key in ENV_ALLOWLIST
        if (value := os.getenv(key)) is not None and value != ""
    }


def _validate_database(path: Path) -> dict[str, int]:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("SQLite backup is empty.")
    if path.stat().st_size > MAX_DATABASE_BYTES:
        raise ValueError("SQLite backup exceeds the 512 MB migration limit.")

    with path.open("rb") as source:
        if source.read(16) != b"SQLite format 3\x00":
            raise ValueError("Uploaded file is not a SQLite database.")

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if not result or result[0] != "ok":
            raise ValueError(f"SQLite quick_check failed: {result!r}")
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required = {"tenants", "applications", "vacancies"}
        if not required.issubset(tables):
            missing = ", ".join(sorted(required - tables))
            raise ValueError(f"SQLite backup is missing required tables: {missing}")
        return {
            "tenants": int(connection.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]),
            "applications": int(
                connection.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
            ),
            "vacancies": int(
                connection.execute("SELECT COUNT(*) FROM vacancies").fetchone()[0]
            ),
        }
    finally:
        connection.close()


def create_sqlite_backup(source: Path, destination: Path) -> dict[str, int]:
    """Create a transactionally consistent SQLite backup and validate it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(str(source))
    destination_connection = sqlite3.connect(str(destination))
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    return _validate_database(destination)


def _database_has_user_data(path: Path) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        for table in ("tenants", "applications", "vacancies"):
            if table in tables and connection.execute(
                f"SELECT EXISTS(SELECT 1 FROM {table} LIMIT 1)"
            ).fetchone()[0]:
                return True
        return False
    finally:
        connection.close()


def _migration_token() -> str:
    return os.getenv("MIGRATION_TOKEN", "").strip()


def _authorized(request: web.Request) -> bool:
    token = _migration_token()
    header = request.headers.get("Authorization", "")
    provided = header[7:] if header.startswith("Bearer ") else ""
    return bool(token and provided and hmac.compare_digest(token, provided))


def _schedule_restart() -> None:
    asyncio.get_running_loop().call_later(2.0, lambda: os._exit(0))


async def receive_migration(request: web.Request) -> web.Response:
    """Receive and atomically install a one-time SQLite + settings bundle."""
    if not env_enabled("MIGRATION_ACCEPT"):
        raise web.HTTPNotFound()
    if not _authorized(request):
        raise web.HTTPUnauthorized(text="Unauthorized migration request.")
    if MIGRATION_MARKER_PATH.exists():
        raise web.HTTPConflict(text="Migration has already completed.")

    db_path = Path(os.getenv("SQLITE_PATH", "data.db"))
    if _database_has_user_data(db_path):
        raise web.HTTPConflict(
            text="Destination database already contains user data; refusing replacement."
        )

    db_path.parent.mkdir(parents=True, exist_ok=True)
    incoming_fd, incoming_name = tempfile.mkstemp(
        prefix=".migration-incoming-", suffix=".db", dir=db_path.parent
    )
    os.close(incoming_fd)
    incoming = Path(incoming_name)
    metadata: dict | None = None
    database_received = False

    try:
        reader = await request.multipart()
        async for part in reader:
            if part.name == "metadata":
                raw = await part.read(decode=True)
                if len(raw) > 1024 * 1024:
                    raise web.HTTPRequestEntityTooLarge(
                        max_size=1024 * 1024, actual_size=len(raw)
                    )
                try:
                    metadata = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise web.HTTPBadRequest(text="Invalid migration metadata.") from exc
            elif part.name == "database":
                total = 0
                with incoming.open("wb") as output:
                    while True:
                        chunk = await part.read_chunk(size=1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_DATABASE_BYTES:
                            raise web.HTTPRequestEntityTooLarge(
                                max_size=MAX_DATABASE_BYTES, actual_size=total
                            )
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                database_received = True

        if not isinstance(metadata, dict) or not database_received:
            raise web.HTTPBadRequest(text="Incomplete migration bundle.")
        settings = metadata.get("settings")
        if not isinstance(settings, dict) or any(
            key not in ENV_ALLOWLIST or not isinstance(value, str)
            for key, value in settings.items()
        ):
            raise web.HTTPBadRequest(text="Invalid runtime settings bundle.")

        counts = _validate_database(incoming)
        supplied_sha = str(metadata.get("database_sha256") or "")
        digest = hashlib.sha256()
        with incoming.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        if not supplied_sha or not hmac.compare_digest(digest.hexdigest(), supplied_sha):
            raise web.HTTPBadRequest(text="Database checksum mismatch.")

        backup = db_path.with_name(f"{db_path.name}.pre-migration-backup")
        if db_path.exists():
            create_sqlite_backup(db_path, backup)

        env_path = Path(
            os.getenv("MIGRATED_ENV_PATH", str(MIGRATED_ENV_PATH))
        )
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_temp = env_path.with_name(f".{env_path.name}.tmp")
        env_temp.write_text(
            json.dumps(settings, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.chmod(env_temp, 0o600)

        try:
            os.replace(incoming, db_path)
            os.replace(env_temp, env_path)
            for suffix in ("-wal", "-shm"):
                Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        except Exception:
            if backup.exists():
                os.replace(backup, db_path)
            env_temp.unlink(missing_ok=True)
            raise

        marker = {
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "database_sha256": digest.hexdigest(),
            "counts": counts,
            "settings_count": len(settings),
        }
        MIGRATION_MARKER_PATH.write_text(
            json.dumps(marker, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        os.chmod(MIGRATION_MARKER_PATH, 0o600)
        logger.info(
            "Migration installed safely: %d tenant, %d application, %d vacancy.",
            counts["tenants"],
            counts["applications"],
            counts["vacancies"],
        )
        _schedule_restart()
        return web.json_response({"ok": True, "counts": counts})
    finally:
        incoming.unlink(missing_ok=True)


async def send_migration_bundle() -> dict:
    """Send the legacy worker's consistent backup to the replacement service."""
    target = os.getenv("MIGRATION_TARGET", "").rstrip("/")
    token = _migration_token()
    source = Path(os.getenv("SQLITE_PATH", "data.db"))
    if not target.startswith("https://") or not token:
        raise RuntimeError("MIGRATION_TARGET or MIGRATION_TOKEN is not configured safely.")
    if not source.exists():
        raise RuntimeError(f"Source database does not exist: {source}")

    with tempfile.TemporaryDirectory(prefix="janobhr-migration-") as temp_dir:
        snapshot = Path(temp_dir) / "data.db"
        counts = await asyncio.to_thread(create_sqlite_backup, source, snapshot)
        digest = hashlib.sha256()
        with snapshot.open("rb") as backup_file:
            for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
                digest.update(chunk)
        metadata = {
            "database_sha256": digest.hexdigest(),
            "counts": counts,
            "settings": collect_runtime_settings(),
        }

        timeout = aiohttp.ClientTimeout(total=180)
        last_error: Exception | None = None
        for attempt in range(1, 31):
            form = aiohttp.FormData()
            form.add_field(
                "metadata",
                json.dumps(metadata, ensure_ascii=False),
                content_type="application/json",
            )
            with snapshot.open("rb") as backup_file:
                form.add_field(
                    "database",
                    backup_file,
                    filename="data.db",
                    content_type="application/octet-stream",
                )
                try:
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.post(
                            f"{target}/internal/render-migration",
                            data=form,
                            headers={"Authorization": f"Bearer {token}"},
                        ) as response:
                            body = await response.text()
                            if response.status == 200:
                                result = json.loads(body)
                                logger.info(
                                    "Migration bundle accepted by destination on attempt %d.",
                                    attempt,
                                )
                                return result
                            if response.status in {401, 409, 413}:
                                raise RuntimeError(
                                    f"Destination rejected migration ({response.status}): {body[:300]}"
                                )
                            last_error = RuntimeError(
                                f"Destination returned {response.status}: {body[:300]}"
                            )
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    last_error = exc
            if attempt < 30:
                await asyncio.sleep(10)
        raise RuntimeError("Migration destination did not become ready.") from last_error


def register_receiver(app: web.Application) -> None:
    app.router.add_post("/internal/render-migration", receive_migration)
