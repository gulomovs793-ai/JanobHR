import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from services import render_migration


class RenderMigrationTests(unittest.TestCase):
    def _source_database(self, path: Path) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE tenants (id INTEGER PRIMARY KEY, company_name TEXT);
                CREATE TABLE applications (id INTEGER PRIMARY KEY, tenant_id INTEGER);
                CREATE TABLE vacancies (id INTEGER PRIMARY KEY, tenant_id INTEGER);
                INSERT INTO tenants VALUES (1, 'Test Company');
                INSERT INTO applications VALUES (1, 1);
                INSERT INTO vacancies VALUES (1, 1);
                """
            )
            connection.commit()
        finally:
            connection.close()

    def test_consistent_backup_is_validated_and_counted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.db"
            destination = Path(temp_dir) / "backup.db"
            self._source_database(source)

            counts = render_migration.create_sqlite_backup(source, destination)

            self.assertEqual(
                counts, {"tenants": 1, "applications": 1, "vacancies": 1}
            )
            self.assertTrue(destination.exists())

    def test_runtime_settings_are_strictly_allowlisted(self):
        with patch.dict(
            os.environ,
            {
                "BOT_TOKEN": "bot-secret",
                "AI_API_KEY": "ai-secret",
                "MIGRATION_TOKEN": "must-not-copy",
                "RENDER_API_KEY": "must-not-copy",
                "WEBHOOK_BASE_URL": "https://old.example",
            },
            clear=True,
        ):
            settings = render_migration.collect_runtime_settings()

        self.assertEqual(
            settings, {"BOT_TOKEN": "bot-secret", "AI_API_KEY": "ai-secret"}
        )

    def test_migrated_settings_do_not_override_explicit_environment(self):
        import config

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "migrated_env.json"
            path.write_text(
                json.dumps({"BOT_TOKEN": "migrated", "AI_MODEL": "migrated-model"}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"MIGRATED_ENV_PATH": str(path), "BOT_TOKEN": "explicit"},
                clear=True,
            ):
                config._load_migrated_runtime_settings()
                self.assertEqual(os.environ["BOT_TOKEN"], "explicit")
                self.assertEqual(os.environ["AI_MODEL"], "migrated-model")

class RenderMigrationReceiverTests(unittest.IsolatedAsyncioTestCase):
    def _database(self, path: Path, *, with_rows: bool) -> None:
        connection = sqlite3.connect(path)
        try:
            connection.executescript(
                """
                CREATE TABLE tenants (id INTEGER PRIMARY KEY, company_name TEXT);
                CREATE TABLE applications (id INTEGER PRIMARY KEY, tenant_id INTEGER);
                CREATE TABLE vacancies (id INTEGER PRIMARY KEY, tenant_id INTEGER);
                """
            )
            if with_rows:
                connection.executescript(
                    """
                    INSERT INTO tenants VALUES (1, 'Migrated Company');
                    INSERT INTO applications VALUES (1, 1);
                    INSERT INTO vacancies VALUES (1, 1);
                    """
                )
            connection.commit()
        finally:
            connection.close()

    async def test_receiver_atomically_installs_valid_bundle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            destination = root / "destination.db"
            source = root / "source.db"
            env_path = root / "migrated_env.json"
            marker_path = root / ".migration_complete.json"
            self._database(destination, with_rows=False)
            self._database(source, with_rows=True)
            database_bytes = source.read_bytes()
            metadata = {
                "database_sha256": hashlib.sha256(database_bytes).hexdigest(),
                "settings": {"BOT_TOKEN": "secret", "AI_MODEL": "test-model"},
            }

            app = web.Application(client_max_size=512 * 1024**2)
            render_migration.register_receiver(app)
            server = TestServer(app)
            client = TestClient(server)
            await client.start_server()
            try:
                form = aiohttp.FormData()
                form.add_field(
                    "metadata",
                    json.dumps(metadata),
                    content_type="application/json",
                )
                form.add_field(
                    "database",
                    database_bytes,
                    filename="data.db",
                    content_type="application/octet-stream",
                )
                with (
                    patch.dict(
                        os.environ,
                        {
                            "MIGRATION_ACCEPT": "1",
                            "MIGRATION_TOKEN": "one-time-token",
                            "SQLITE_PATH": str(destination),
                            "MIGRATED_ENV_PATH": str(env_path),
                        },
                        clear=False,
                    ),
                    patch.object(
                        render_migration, "MIGRATION_MARKER_PATH", marker_path
                    ),
                    patch.object(render_migration, "_schedule_restart") as restart,
                ):
                    response = await client.post(
                        "/internal/render-migration",
                        data=form,
                        headers={"Authorization": "Bearer one-time-token"},
                    )
                    payload = await response.json()

                self.assertEqual(response.status, 200)
                self.assertEqual(payload["counts"]["tenants"], 1)
                self.assertEqual(
                    json.loads(env_path.read_text(encoding="utf-8")),
                    metadata["settings"],
                )
                self.assertTrue(marker_path.exists())
                connection = sqlite3.connect(destination)
                try:
                    company = connection.execute(
                        "SELECT company_name FROM tenants WHERE id = 1"
                    ).fetchone()[0]
                finally:
                    connection.close()
                self.assertEqual(company, "Migrated Company")
                restart.assert_called_once()
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
