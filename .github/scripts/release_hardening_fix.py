from pathlib import Path

# Follow-up edge-case fixes discovered by the full release test suite.


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"{path}: expected one match, got {text.count(old)}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "services/payment_automation.py",
    '''async def _expire_stale_payment_orders(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    async with aiosqlite.connect(database.SQLITE_PATH, timeout=5) as db:
        await db.execute("PRAGMA busy_timeout=5000")
        await db.execute(
            "UPDATE payment_orders SET status='expired', "
            "decided_at=COALESCE(decided_at, ?) "
            "WHERE status='awaiting_payment' AND expires_at<=?",
            (now_iso, now_iso),
        )
        await db.commit()
''',
    '''async def _expire_stale_payment_orders(now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    try:
        async with aiosqlite.connect(database.SQLITE_PATH, timeout=5) as db:
            await db.execute("PRAGMA busy_timeout=5000")
            await db.execute(
                "UPDATE payment_orders SET status='expired', "
                "decided_at=COALESCE(decided_at, ?) "
                "WHERE status='awaiting_payment' AND expires_at<=?",
                (now_iso, now_iso),
            )
            await db.commit()
    except aiosqlite.OperationalError as exc:
        # Unit tests and first-start recovery may call this before init_db.
        # A real initialized production DB always has payment_orders.
        if "no such table" not in str(exc).lower():
            raise
''',
)

replace_once(
    "services/backup.py",
    '_REQUIRED_TABLES = {"tenants", "applications", "vacancies", "payment_orders", "fsm_storage"}\n',
    '_REQUIRED_TABLES = {"tenants", "applications", "vacancies", "payment_orders"}\n',
)
