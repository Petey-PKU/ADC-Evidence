from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.backup import backup_database, sha256_file


class DatabaseBackupTests(unittest.TestCase):
    def test_backup_is_readable_and_has_matching_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database = root / "source.db"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("CREATE TABLE example (value TEXT NOT NULL)")
                connection.execute("INSERT INTO example VALUES ('adc')")
                connection.commit()

            result = backup_database(
                database,
                root / "backups",
                timestamp=datetime(2026, 8, 20, 1, 2, 3, tzinfo=UTC),
            )
            backup = Path(str(result["backup_path"]))
            manifest_path = backup.with_suffix(".json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            with closing(sqlite3.connect(backup)) as connection:
                value = connection.execute("SELECT value FROM example").fetchone()[0]
            self.assertEqual(value, "adc")
            self.assertEqual(manifest["sha256"], sha256_file(backup))
            self.assertEqual(manifest["database"], backup.name)

    def test_missing_database_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            with self.assertRaises(FileNotFoundError):
                backup_database(root / "missing.db", root / "backups")


if __name__ == "__main__":
    unittest.main()
