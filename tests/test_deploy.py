from __future__ import annotations
from tests.support import WorkspaceTemporaryDirectory

import unittest
from pathlib import Path
from unittest.mock import patch

from adc_evidence.config import DEFAULT_SEED_PATH, PUBLIC_DATABASE_ARCHIVE_PATH, PUBLIC_DATABASE_FILENAME
from adc_evidence.workbench import sync_public_seed_facts
from adc_evidence.deploy import ensure_runtime_assets, restore_public_snapshot_archive


class DeploymentBootstrapTests(unittest.TestCase):
    def test_clean_runtime_bootstraps_demo_without_overwriting_on_second_run(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database = root / "processed" / "adc.db"
            index = root / "index"
            first = ensure_runtime_assets(
                database_path=database,
                seed_path=DEFAULT_SEED_PATH,
                index_path=index,
                bootstrap_backend="hashing",
            )
            second = ensure_runtime_assets(
                database_path=database,
                seed_path=DEFAULT_SEED_PATH,
                index_path=index,
                bootstrap_backend="hashing",
            )
            self.assertEqual(first["adc_count"], 10)
            self.assertEqual(first["chunk_count"], 10)
            self.assertTrue(first["corpus_built"])
            self.assertTrue(first["index_built"])
            self.assertFalse(second["corpus_built"])
            self.assertFalse(second["index_built"])
            self.assertEqual(second["embedding_backend"], "hashing")
            self.assertEqual(first["seed_fact_sync"]["facts_created"], 98)
            self.assertEqual(first["seed_fact_sync"]["evidence_created"], 98)
            self.assertEqual(second["seed_fact_sync"]["facts_created"], 0)
            self.assertEqual(second["seed_fact_sync"]["idempotent_groups"], 100)

    def test_public_default_missing_snapshot_fails_without_demo_fallback(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / "processed" / "adc_public_2026-09-30.db"
            index = Path(temporary_directory) / "index"
            with patch("adc_evidence.deploy.DEFAULT_DATABASE_PATH", database), patch(
                "adc_evidence.deploy.PUBLIC_DATABASE_ARCHIVE_PATH",
                Path(temporary_directory) / "missing.db.zip",
            ):
                with self.assertRaises(FileNotFoundError):
                    ensure_runtime_assets(
                        database_path=database,
                        index_path=index,
                        allow_seed_bootstrap=False,
                    )

    def test_tracked_snapshot_archive_restores_verified_database(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            database = Path(temporary_directory) / PUBLIC_DATABASE_FILENAME
            result = restore_public_snapshot_archive(
                database_path=database,
                archive_path=PUBLIC_DATABASE_ARCHIVE_PATH,
            )
            self.assertTrue(result["restored"])
            self.assertTrue(database.is_file())
            self.assertEqual(result["sha256"], "d28939138a67f1493553a24af49198f8115bc3026591f9a2b97c3e5568ef6482")

    def test_existing_snapshot_skips_seed_sync_when_requested(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database = root / "processed" / "snapshot.db"
            index = root / "index"
            sync_public_seed_facts(database, DEFAULT_SEED_PATH)
            first = ensure_runtime_assets(
                database_path=database,
                index_path=index,
                allow_seed_bootstrap=False,
            )
            self.assertTrue(first["seed_fact_sync"]["skipped"])
            self.assertEqual(first["seed_fact_sync"]["facts_created"], 0)


if __name__ == "__main__":
    unittest.main()
