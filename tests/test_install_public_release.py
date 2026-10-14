from __future__ import annotations

import json
import shutil
import unittest
import zipfile
from pathlib import Path

from scripts.install_public_release import (
    _member_path,
    _runtime_members,
    release_asset_url,
)


class PublicReleaseInstallerTests(unittest.TestCase):
    def test_release_asset_url_encodes_tag_and_asset(self) -> None:
        self.assertEqual(
            release_asset_url(tag="v0.7.0", asset="adc-public-2026-09-30.zip"),
            "https://github.com/Petey-PKU/ADC-Evidence/releases/download/v0.7.0/adc-public-2026-09-30.zip",
        )

    def test_member_path_rejects_traversal(self) -> None:
        root = Path.cwd() / ".test_tmp" / "installer-traversal"
        root.mkdir(parents=True, exist_ok=True)
        try:
            with self.assertRaises(ValueError):
                _member_path(root, "../outside.db")
            with self.assertRaises(ValueError):
                _member_path(root, "C:/outside.db")
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_runtime_members_follow_manifest(self) -> None:
        root = Path.cwd() / ".test_tmp" / "installer-members"
        root.mkdir(parents=True, exist_ok=True)
        try:
            archive_path = root / "release.zip"
            manifest = {
                "application": {
                    "database_path": "data/processed/adc_public.db",
                    "index_path": "artifacts/vector_index/public",
                }
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("RELEASE_MANIFEST.json", json.dumps(manifest))
                archive.writestr("data/processed/adc_public.db", b"db")
                archive.writestr("artifacts/vector_index/public/manifest.json", b"{}")
            with zipfile.ZipFile(archive_path) as archive:
                database, members = _runtime_members(archive)
            self.assertEqual(database, "data/processed/adc_public.db")
            self.assertEqual(
                members,
                [
                    "data/processed/adc_public.db",
                    "artifacts/vector_index/public/manifest.json",
                ],
            )
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
