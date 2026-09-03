from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor in {path}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


database_anchor = '''        if "customer_notified_at" not in payment_columns:\n            await db.execute(\n                "ALTER TABLE payment_orders ADD COLUMN customer_notified_at TEXT"\n            )\n        cursor = await db.execute("PRAGMA table_info(business_leads)")\n'''

database_replacement = '''        if "customer_notified_at" not in payment_columns:\n            await db.execute(\n                "ALTER TABLE payment_orders ADD COLUMN customer_notified_at TEXT"\n            )\n\n        # Defense-in-depth for payment routing: even if application-level locking\n        # regresses later, SQLite itself must never allow two LIVE orders to own\n        # the same exact incoming amount. Historical duplicates from older code\n        # are ambiguous, so mark every still-live duplicate for manual review\n        # before creating the partial UNIQUE index.\n        duplicate_now = datetime.now(timezone.utc).isoformat()\n        cursor = await db.execute(\n            "SELECT amount FROM payment_orders WHERE status='awaiting_payment' "\n            "GROUP BY amount HAVING COUNT(*) > 1"\n        )\n        for (duplicate_amount,) in await cursor.fetchall():\n            logger.error(\n                "Duplicate live payment amount migrationda topildi: %s; needs_review qilindi.",\n                duplicate_amount,\n            )\n            await db.execute(\n                "UPDATE payment_orders SET status='needs_review', "\n                "decided_at=COALESCE(decided_at, ?) "\n                "WHERE amount=? AND status='awaiting_payment'",\n                (duplicate_now, duplicate_amount),\n            )\n        await db.execute(\n            "CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_orders_awaiting_amount "\n            "ON payment_orders(amount) WHERE status='awaiting_payment'"\n        )\n\n        cursor = await db.execute("PRAGMA table_info(business_leads)")\n'''
replace_once(
    "services/database.py",
    database_anchor,
    database_replacement,
    "payment partial unique index migration",
)


test_anchor = '''    async def test_parallel_orders_never_share_exact_amount(self):\n        first, second = await asyncio.gather(\n            create_payment_order(self.tenant_a, 599_000, plan_code="growth"),\n            create_payment_order(self.tenant_b, 599_000, plan_code="growth"),\n        )\n        self.assertNotEqual(first["amount"], second["amount"])\n\n'''

test_replacement = test_anchor + '''    async def test_db_rejects_duplicate_live_payment_amount(self):\n        first = await create_payment_order(self.tenant_a, 599_000, plan_code="growth")\n        aiosqlite = __import__("aiosqlite")\n        async with aiosqlite.connect(self.db_path) as db:\n            with self.assertRaises(aiosqlite.IntegrityError):\n                await db.execute(\n                    "INSERT INTO payment_orders "\n                    "(tenant_id, order_code, base_amount, amount, plan_code, billing_months, "\n                    "status, created_at, expires_at) "\n                    "VALUES (?, ?, ?, ?, ?, ?, 'awaiting_payment', ?, ?)",\n                    (\n                        self.tenant_b,\n                        "JH-INDEX-TEST",\n                        599_000,\n                        first["amount"],\n                        "growth",\n                        1,\n                        "2026-09-03T00:00:00+00:00",\n                        "2099-09-03T00:20:00+00:00",\n                    ),\n                )\n\n'''
replace_once(
    "tests/test_release_hardening.py",
    test_anchor,
    test_replacement,
    "payment database uniqueness regression test",
)
