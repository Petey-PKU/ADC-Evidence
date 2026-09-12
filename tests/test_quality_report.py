from __future__ import annotations

import json
import unittest
from pathlib import Path

from adc_evidence.repository import data_quality_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QualityReportTests(unittest.TestCase):
    def test_committed_quality_report_matches_committed_database(self) -> None:
        report_path = PROJECT_ROOT / "data" / "processed" / "data_quality_report.json"
        database_path = PROJECT_ROOT / "data" / "processed" / "adc_evidence.db"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["report_scope"], "current_committed_demo_seed")
        self.assertEqual(report["database_metrics"], data_quality_metrics(database_path))


if __name__ == "__main__":
    unittest.main()
