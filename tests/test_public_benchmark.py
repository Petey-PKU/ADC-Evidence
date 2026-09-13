from __future__ import annotations

import json
import unittest
from pathlib import Path

from adc_evidence.evaluation.public_benchmark import (
    benchmark_manifest,
    compare_public_benchmark_reports,
    load_public_benchmark,
    score_public_benchmark,
)
from scripts.prepare_public_benchmark_review import prepare_packet
from scripts.validate_public_benchmark import validate_public_benchmark
from tests.support import WorkspaceTemporaryDirectory


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

    def test_checked_in_manifest_binds_questions_and_catalog(self) -> None:
        result = validate_public_benchmark(
            BENCHMARK,
            ROOT / "data" / "annotations" / "public_benchmark_v1.manifest.json",
            catalog_path=ROOT / "data" / "public" / "marketed_adc_catalog.csv",
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["question_count"], 98)

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

    def test_answer_field_accuracy_scores_structured_claims(self) -> None:
        row = load_public_benchmark(BENCHMARK)[0]
        output = {
            "question_id": row["question_id"],
            "route": row["expected_route"],
            "status": "answered",
            "citation_source_record_ids": [item["source_record_id"] for item in row["evidence_sources"]],
            "claims": [{
                "predicate": "adc.target",
                "value": [row["standard_answer"]["value"]],
            }],
        }
        score = score_public_benchmark([output], [row])
        self.assertEqual(score["answer_field_accuracy"], 1.0)
        self.assertEqual(score["answer_exact_accuracy"], 1.0)

    def test_partial_answer_policy_is_reflected_in_metrics(self) -> None:
        row = {
            "question_id": "partial-comparison",
            "split": "dev",
            "category": "comparison",
            "question": "compare two payloads",
            "expected_route": "comparison",
            "expected_status": ["answered"],
            "standard_answer": {"kind": "comparison", "field": "payload_name", "values": {"a": "MMAE", "b": "DM1"}},
            "allowed_answers": [],
            "evidence_sources": [],
            "allow_partial": True,
            "should_refuse": False,
            "human_scoring": {"status": "pending", "primary": None, "secondary": None, "adjudicated": None},
            "scoring": {"primary_metric": "answer_field_accuracy"},
        }
        output = {
            "question_id": row["question_id"],
            "route": "comparison",
            "status": "answered",
            "claims": [{"subject_id": "a", "predicate": "adc.payload_name", "value": "MMAE"}],
        }
        score = score_public_benchmark([output], [row])
        self.assertEqual(score["answer_field_accuracy"], 0.5)
        self.assertEqual(score["answer_exact_accuracy"], 0.0)
        row["allow_partial"] = False
        score = score_public_benchmark([output], [row])
        self.assertEqual(score["answer_field_accuracy"], 0.0)

    def test_review_packet_leaves_human_verdicts_pending(self) -> None:
        rows = load_public_benchmark(BENCHMARK)[:2]
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            questions = root / "questions.jsonl"
            report = root / "report.json"
            questions.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
            report.write_text(json.dumps({"questions": [
                {"question_id": row["question_id"], "route": row["expected_route"], "status": "answered", "answer": "x"}
                for row in rows
            ]}), encoding="utf-8")
            packet, manifest = prepare_packet(questions, report)
        finally:
            temporary.cleanup()
        self.assertEqual(manifest["status"], "awaiting_independent_human_review")
        self.assertTrue(all(item["review"]["status"] == "pending" for item in packet))
        self.assertTrue(all(item["review"]["review_origin"] is None for item in packet))

    def test_paired_comparison_reports_differences(self) -> None:
        rows = load_public_benchmark(BENCHMARK)[:1]
        gold = rows[0]
        system = [{"question_id": gold["question_id"], "route": gold["expected_route"], "status": "answered", "citation_source_record_ids": [], "claims": [{"predicate": "adc.target", "value": [gold["standard_answer"]["value"]]}]}]
        baseline = [{"question_id": gold["question_id"], "route": "literature_evidence", "status": "answered", "citation_source_record_ids": [], "claims": []}]
        comparison = compare_public_benchmark_reports(system, baseline, rows)
        self.assertEqual(comparison["paired_metrics"]["route"]["difference"], 1.0)
        self.assertEqual(comparison["paired_metrics"]["answer"]["system_rate"], 1.0)
        self.assertIn("mcnemar_exact_two_sided_pvalue", comparison["paired_metrics"]["route"]["paired_statistics"])


if __name__ == "__main__":
    unittest.main()
