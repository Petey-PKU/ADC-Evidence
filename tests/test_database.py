import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from adc_evidence.config import DEFAULT_SEED_PATH
from adc_evidence.database import (
    database_stats,
    initialize_database,
    load_seed_records,
    search_adcs,
)
from adc_evidence.models import ADCRecord


class DatabaseTests(unittest.TestCase):
    def test_seed_file_contains_ten_valid_records(self) -> None:
        records = load_seed_records(DEFAULT_SEED_PATH)
        self.assertEqual(len(records), 10)
        self.assertEqual({record.target for record in records}, {"HER2", "TROP2"})

    def test_negative_dar_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ADCRecord(
                adc_id="invalid",
                adc_name="Invalid ADC",
                target="HER2",
                dar=-1,
            )

    def test_initialize_and_search_by_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.db"
            imported = initialize_database(database_path, DEFAULT_SEED_PATH)

            self.assertEqual(imported, 10)
            results = search_adcs(database_path, "T-DXd")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["adc_name"], "Trastuzumab deruxtecan")

    def test_initialize_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.db"
            initialize_database(database_path, DEFAULT_SEED_PATH)
            initialize_database(database_path, DEFAULT_SEED_PATH)

            stats = database_stats(database_path)
            self.assertEqual(stats["adc_count"], 10)
            self.assertEqual(stats["target_count"], 2)

    def test_search_by_target_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.db"
            initialize_database(database_path, DEFAULT_SEED_PATH)

            self.assertEqual(len(search_adcs(database_path, "HER2")), 5)
            self.assertEqual(len(search_adcs(database_path, "DXd")), 2)


if __name__ == "__main__":
    unittest.main()

