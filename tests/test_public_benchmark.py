from __future__ import annotations

import json
import unittest
from pathlib import Path

from adc_evidence.evaluation.public_benchmark import (
    benchmark_manifest,
    load_public_benchmark,
    score_public_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "data" / "annotations" / "public_benchmark_v1.jsonl"


class PublicBenchmarkTests(unittest.TestCase):
    def test_checked_in_public_benchmark_has_required_scope(self) -> None:
        rows = load_public_benchmark(BENCHMARK)
        self.assertGreaterEqual(len(rows), 80)
        categories = {str(row["category"]) for row in rows}
        self.assertEqual(
            categories,
            {"structured_fact", "comparison", "trial_lookup", "literature_evidence", "safety_refusal"},
        )
        self.assertTrue(all(row["human_scoring"]["status"] == "pending" for row in rows))

    def test_manifest_records_exposed_use_and_metrics(self) -> None:
        rows = load_public_benchmark(BENCHMARK)
        manifest = benchmark_manifest(
            rows,
            catalog_sha256="sha256:test",
            database_data_version=None,
            requested_as_of="2026-09-30",
        )
        self.assertFalse(manifest["evaluation_use"]["eligible_for_unseen_test_claim"])
        self.assertIn("evidence_recall", manifest["metrics"])

    def test_automatic_scoring_requires_exact_question_identity(self) -> None:
        rows = load_public_benchmark(BENCHMARK)[:2]
        outputs = [
            {
                "question_id": row["question_id"],
                "route": row["expected_route"],
                "status": row["expected_status"][0],
                "citation_source_record_ids": [
                    item["source_record_id"] for item in row["evidence_sources"]
                ],
            }
            for row in rows
        ]
        score = score_public_benchmark(outputs, rows)
        self.assertEqual(score["question_count"], 2)
        self.assertEqual(score["route_accuracy"], 1.0)
        self.assertIn("structured_fact", score["by_category"])
        with self.assertRaises(ValueError):
            score_public_benchmark(outputs[:1], rows)


if __name__ == "__main__":
    unittest.main()
