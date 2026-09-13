from __future__ import annotations

import hashlib
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.package_public_release import _release_readme, package_release
from scripts.verify_public_release import verify_release
from tests.support import WorkspaceTemporaryDirectory


class PublicReleaseTests(unittest.TestCase):
    def test_release_readme_contains_direct_use_paths(self) -> None:
        readme = _release_readme("2026-09-30")
        self.assertIn("ADC_DATABASE_PATH", readme)
        self.assertIn("ADC_VECTOR_INDEX_PATH", readme)
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


if __name__ == "__main__":
    unittest.main()
