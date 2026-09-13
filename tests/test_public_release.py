from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.package_public_release import (
    _release_readme,
    _sanitize_database_for_release,
    _validate_database_catalog_binding,
    package_release,
)
from scripts.verify_public_release import _database_absolute_path_count, verify_release
from tests.support import WorkspaceTemporaryDirectory


class PublicReleaseTests(unittest.TestCase):
    def test_database_catalog_binding_rejects_stale_source_url(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            catalog = root / "catalog.csv"
            catalog.write_text(
                "adc_id,adc_name,target,antibody,linker_name,linker_type,payload_name,payload_class,dar,indication,development_status,company,source_url,data_review_status\n"
                "adc_001,Example,HER2,Ab,linker,cleavable,payload,class,4.0,cancer,approved,Company,https://new.example/source,needs_review\n",
                encoding="utf-8",
            )
            database = root / "database.db"
            with sqlite3.connect(database) as connection:
                connection.execute(
                    "CREATE TABLE adcs (adc_id TEXT, adc_name TEXT, target TEXT, antibody TEXT, linker_name TEXT, linker_type TEXT, payload_name TEXT, payload_class TEXT, dar TEXT, indication TEXT, development_status TEXT, company TEXT, source_url TEXT, data_review_status TEXT)"
                )
                connection.execute(
                    "INSERT INTO adcs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("adc_001", "Example", "HER2", "Ab", "linker", "cleavable", "payload", "class", "4.0", "cancer", "approved", "Company", "https://old.example/source", "needs_review"),
                )
            with self.assertRaisesRegex(ValueError, "field binding drift"):
                _validate_database_catalog_binding(database, catalog)
        finally:
            temporary.cleanup()

    def test_release_readme_contains_direct_use_paths(self) -> None:
        readme = _release_readme("2026-09-30")
        self.assertIn("ADC_DATABASE_PATH", readme)
        self.assertIn("ADC_VECTOR_INDEX_PATH", readme)
        self.assertIn("ADC_OFFLINE_ONLY", readme)
        self.assertIn('ADC_LLM_BACKEND = "extractive"', readme)
        self.assertIn("RELEASE_MANIFEST.json", readme)

    def test_package_contains_manifest_and_checksummed_files(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            source = root / "source.txt"
            source.write_text("public fixture", encoding="utf-8")
            output = root / "release.zip"
            inventory = {
                "schema_version": "public-adc-release-v1",
                "dataset_as_of": "2026-09-30",
                "retrieval_corpus_version": "corpus_test",
                "files": [{
                    "archive_path": "data/source.txt",
                    "size_bytes": len(b"public fixture"),
                    "sha256": "sha256:" + hashlib.sha256(b"public fixture").hexdigest(),
                }],
            }
            with patch(
                "scripts.package_public_release.build_release_inventory",
                return_value=([(source, "data/source.txt")], inventory),
            ):
                package_release(
                    database=root / "db",
                    index_path=root / "index",
                    catalog=root / "catalog",
                    benchmark_manifest=root / "benchmark",
                    output=output,
                    as_of="2026-09-30",
                )
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("data/source.txt"), b"public fixture")
                manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
                self.assertEqual(manifest["retrieval_corpus_version"], "corpus_test")
                self.assertIn("RELEASE_README.md", archive.namelist())
        finally:
            temporary.cleanup()

    def test_verify_release_checks_manifest_entries(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            source = root / "source.txt"
            source.write_text("public fixture", encoding="utf-8")
            output = root / "release.zip"
            inventory = {
                "schema_version": "public-adc-release-v1",
                "dataset_as_of": "2026-09-30",
                "retrieval_corpus_version": "corpus_test",
                "files": [{
                    "archive_path": "data/source.txt",
                    "size_bytes": len(b"public fixture"),
                    "sha256": "sha256:" + hashlib.sha256(b"public fixture").hexdigest(),
                }],
            }
            with patch(
                "scripts.package_public_release.build_release_inventory",
                return_value=([(source, "data/source.txt")], inventory),
            ):
                package_release(
                    database=root / "db",
                    index_path=root / "index",
                    catalog=root / "catalog",
                    benchmark_manifest=root / "benchmark",
                    output=output,
                    as_of="2026-09-30",
                )
            report = verify_release(output)
            self.assertEqual(report["status"], "verified")
            self.assertEqual(report["checked_file_count"], 1)
        finally:
            temporary.cleanup()

    def test_sanitized_database_redacts_local_paths(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            source = root / "source.db"
            destination = root / "release.db"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE source_records (raw_path TEXT)")
                connection.execute("INSERT INTO source_records VALUES (?)", (r"C:\\Users\\example\\private\\raw.json",))
                connection.execute("CREATE TABLE ingestion_runs (parameters_json TEXT)")
                connection.execute("INSERT INTO ingestion_runs VALUES (?)", (json.dumps({"database": r"C:\\Users\\example\\private\\db.sqlite"}),))
            _sanitize_database_for_release(source, destination)
            with sqlite3.connect(source) as connection:
                self.assertIn("Users", connection.execute("SELECT raw_path FROM source_records").fetchone()[0])
            with sqlite3.connect(destination) as connection:
                self.assertEqual(connection.execute("SELECT raw_path FROM source_records").fetchone()[0], "raw/source_records/raw.json")
                self.assertNotIn("Users", connection.execute("SELECT parameters_json FROM ingestion_runs").fetchone()[0])
        finally:
            temporary.cleanup()

    def test_release_verifier_detects_database_absolute_paths(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            source = Path(temporary.name) / "source.db"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE source_records (raw_path TEXT)")
                connection.execute("INSERT INTO source_records VALUES (?)", (r"C:\\Users\\example\\raw.json",))
            count = _database_absolute_path_count(source.read_bytes())
        finally:
            temporary.cleanup()
        self.assertEqual(count, 1)

    def test_release_verifier_allows_relative_windows_parameters(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            source = Path(temporary.name) / "source.db"
            with sqlite3.connect(source) as connection:
                connection.execute("CREATE TABLE ingestion_runs (parameters_json TEXT)")
                connection.execute(
                    "INSERT INTO ingestion_runs VALUES (?)",
                    (json.dumps({"database": r"data\\processed\\snapshot.db"}),),
                )
            count = _database_absolute_path_count(source.read_bytes())
        finally:
            temporary.cleanup()
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
