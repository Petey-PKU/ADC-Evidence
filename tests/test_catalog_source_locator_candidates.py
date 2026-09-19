from __future__ import annotations

import json
import unittest
from pathlib import Path


class CatalogSourceLocatorCandidateTests(unittest.TestCase):
    def test_candidates_are_explicitly_pending_and_cover_eight_core_records(self) -> None:
        path = Path(__file__).resolve().parents[1] / "data/public/catalog_source_locator_candidates.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 84)
        self.assertEqual({row["adc_id"] for row in rows}, {"adc_001", "adc_002", "adc_004", "adc_007", "adc_008", "adc_009", "adc_010", "adc_011", "adc_012", "adc_013", "adc_014", "adc_015"})
        self.assertTrue(all(row["review_status"] == "pending_independent_primary_source_review" for row in rows))
        self.assertTrue(all(row["source_tier"] in {"regulator_label", "regulator_review"} for row in rows))
        self.assertTrue(all(row["support_status"] in {"candidate_direct", "partial"} for row in rows))
        self.assertTrue(all(row["source_url"].startswith("https://www.accessdata.fda.gov/") for row in rows))
        self.assertFalse(any("verdict" in row for row in rows))


if __name__ == "__main__":
    unittest.main()
