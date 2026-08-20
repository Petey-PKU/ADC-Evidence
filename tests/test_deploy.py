from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from adc_evidence.config import DEFAULT_SEED_PATH
from adc_evidence.deploy import ensure_runtime_assets


class DeploymentBootstrapTests(unittest.TestCase):
    def test_clean_runtime_bootstraps_demo_without_overwriting_on_second_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
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


if __name__ == "__main__":
    unittest.main()

