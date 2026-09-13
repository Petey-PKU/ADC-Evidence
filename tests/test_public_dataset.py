from __future__ import annotations

import unittest
from pathlib import Path

from scripts.build_public_dataset import classify_literature_text
from adc_evidence.models import ADCRecord
from scripts.build_public_dataset import (
    DEFAULT_CATALOG,
    _catalog_summary,
    _parse_date,
    build_parser,
)


class PublicDatasetTests(unittest.TestCase):
    def test_literature_topic_rules_cover_mechanism_efficacy_and_safety(self) -> None:
        labels = classify_literature_text(
            "Preclinical mechanism and efficacy study",
            "Safety and adverse event results included.",
        )
        self.assertEqual(set(labels), {"mechanism", "efficacy", "safety"})
        self.assertIn("mechanism", labels["mechanism"])

    def test_catalog_has_unique_valid_public_records(self) -> None:
        summary = _catalog_summary(DEFAULT_CATALOG)
        self.assertGreaterEqual(summary["row_count"], 20)
        self.assertEqual(len(summary["adc_ids"]), len(set(summary["adc_ids"])))

        import csv

        with DEFAULT_CATALOG.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            ADCRecord.model_validate(row)

    def test_catalog_contains_active_and_historical_statuses(self) -> None:
        summary = _catalog_summary(DEFAULT_CATALOG)
        self.assertIn("marketed", summary["status_counts"])
        self.assertIn("withdrawn", summary["status_counts"])

    def test_as_of_parser_rejects_invalid_dates(self) -> None:
        self.assertEqual(_parse_date("2026-09-30").isoformat(), "2026-09-30")
        with self.assertRaises(ValueError):
            _parse_date("2026/09/30")

    def test_builder_defaults_to_requested_future_window(self) -> None:
        args = build_parser().parse_args([])
        self.assertEqual(args.as_of, "2026-09-30")
        self.assertFalse(args.include_adcdb)


if __name__ == "__main__":
    unittest.main()
