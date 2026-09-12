from __future__ import annotations

import re
import unittest
from pathlib import Path

from adc_evidence.evaluation.artifact_manifest import build_public_artifact_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ArtifactManifestTests(unittest.TestCase):
    def test_manifest_contains_public_hash_inventory_only(self) -> None:
        manifest = build_public_artifact_manifest(PROJECT_ROOT)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", str(manifest["code_commit"])))
        self.assertEqual(manifest["tracked_file_count"], len(manifest["files"]))
        self.assertEqual(manifest["public_hygiene"]["status"], "clean")
        for row in manifest["files"]:
            self.assertFalse(Path(str(row["path"])).is_absolute())
            self.assertTrue(str(row["sha256"]).startswith("sha256:"))
        self.assertNotIn("reviewer", str(manifest).lower())


if __name__ == "__main__":
    unittest.main()
