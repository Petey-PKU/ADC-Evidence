from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.package_public_release import (
    _release_readme,
    _runtime_files,
    _sanitize_database_for_release,
    _validate_database_catalog_binding,
    package_release,
)
from scripts.verify_public_release import _database_absolute_path_count, verify_release
from scripts.build_public_dataset import classify_public_literature
from tests.support import WorkspaceTemporaryDirectory
from adc_evidence.database import initialize_database
from adc_evidence.rag.documents import build_and_persist_corpus
from adc_evidence.rag.vector_index import build_vector_index
from adc_evidence.workbench import sync_public_seed_facts


class PublicReleaseTests(unittest.TestCase):
    def test_runtime_inventory_excludes_untracked_and_non_runtime_files(self) -> None:
        from scripts import package_public_release as module

        required = [
            "pyproject.toml", "README.md", "configs/entities.json", "configs/evidence_policy.json",
            "scripts/run_public_release.py", "scripts/verify_public_release.py",
            "src/adc_evidence/__init__.py", "src/adc_evidence/app.py",
        ]
        with WorkspaceTemporaryDirectory() as directory:
            root = Path(directory)
            for name in [*required, "src/adc_evidence/local_cache.py", "configs/local.json", ".env"]:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("public fixture", encoding="utf-8")
            with patch.object(module, "ROOT", root), patch.object(
                module.subprocess, "check_output",
                side_effect=[("\0".join([*required, "configs/local.json", ".env"]) + "\0").encode(), "abc\n", b""],
            ):
                files, metadata = _runtime_files()
            self.assertEqual({name for _, name in files}, set(required))
            self.assertFalse(metadata["dependencies_bundled"])

    def test_extracted_release_answers_without_checkout_or_network(self) -> None:
        project = Path(__file__).resolve().parents[1]
        catalog = project / "data/sample/adcs.csv"
        with WorkspaceTemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "custom.db"
            index = root / "custom-index"
            initialize_database(database, catalog)
            sync_public_seed_facts(database, catalog)
            classify_public_literature(database)
            build_and_persist_corpus(database_path=database)
            build_vector_index(database_path=database, index_path=index, backend="hashing")
            benchmark = root / "benchmark.json"
            benchmark.write_text('{}', encoding="utf-8")
            archive_path = root / "release.zip"
            package_release(
                database=database, index_path=index, catalog=catalog,
                benchmark_manifest=benchmark, output=archive_path, as_of="2026-09-13",
            )
            self.assertTrue(verify_release(archive_path)["bundled_application_present"])
            extracted = root / "standalone"
            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extracted)
            # Isolated Python ignores PYTHONPATH; block sockets to prove the
            # bundled CLI answers without a project/model network dependency.
            command = (
                "import os, runpy, socket, sys; "
                "socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
                "os.environ['ADC_OFFLINE_ONLY']='false'; os.environ['ADC_LLM_BACKEND']='openai'; "
                "sys.argv=[sys.argv[1], '--question', 'T-DXd 的靶点和载荷是什么？']; "
                "runpy.run_path(sys.argv[0], run_name='__main__'); "
                "import adc_evidence; from pathlib import Path; "
                "assert Path(adc_evidence.__file__).resolve().is_relative_to(Path(sys.argv[0]).resolve().parents[1])"
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-c", command, str(extracted / "scripts/run_public_release.py")],
                cwd=root, check=True, capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            answer = json.loads(completed.stdout)
            self.assertEqual(answer["status"], "answered", answer)
            self.assertEqual(answer["question"], "T-DXd 的靶点和载荷是什么？")
            self.assertEqual(answer["generator_backend"], "structured")
            self.assertEqual(
                {claim["predicate"]: claim["value"] for claim in answer["claims"]},
                {"adc.target": ["HER2"], "adc.payload_name": ["DXd"]},
            )

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
