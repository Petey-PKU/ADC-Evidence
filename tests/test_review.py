from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from adc_evidence.database import REVIEW_SCHEMA_VERSION, create_database
from adc_evidence.review.bad_cases import (
    build_bad_case_report,
    render_bad_case_markdown,
)
from adc_evidence.review.export_reviews import export_reviews
from adc_evidence.review.repository import (
    import_generation_report,
    import_retrieval_report,
    list_review_items,
    review_stats,
    save_expert_review,
)


def generation_report(
    answer: str = "- 靶点是 HER2。[S1]",
    *,
    run_id: str | None = None,
    model: str = "deterministic-extractive-v1",
) -> dict[str, object]:
    report: dict[str, object] = {
        "evaluated_at": "2026-01-01T00:00:00+00:00",
        "backend": "extractive",
        "requested_model": model,
        "retrieval_mode": "sparse",
        "top_k": 5,
        "questions": [
            {
                "question_id": "gen_001",
                "category": "adc_profile",
                "question": "T-DXd 的靶点是什么？",
                "should_refuse": False,
                "status": "answered",
                "refusal_reason": None,
                "expected_document_ids": ["adc_profile:adc_001"],
                "cited_document_ids": ["adc_profile:adc_001"],
                "citation_valid": True,
                "gold_citation_hit": True,
                "key_fact_recall": 0.5,
                "latency_ms": 3,
                "model": model,
                "usage": {},
                "response_id": None,
                "answer": answer,
            }
        ],
    }
    if run_id:
        report["run_id"] = run_id
    return report


def retrieval_report() -> dict[str, object]:
    return {
        "evaluated_at": "2026-01-01T00:00:00+00:00",
        "top_k": 10,
        "results": [
            {
                "mode": "sparse",
                "sparse_weight": None,
                "dense_weight": None,
                "questions": [
                    {
                        "question_id": "ret_001",
                        "category": "adc_profile",
                        "question": "T-DXd 的靶点是什么？",
                        "expected_document_ids": ["adc_profile:adc_001"],
                        "retrieved_document_ids": [
                            "adc_profile:adc_002",
                            "adc_profile:adc_001",
                        ],
                        "reciprocal_rank": 0.5,
                        "ndcg": 0.6309,
                        "hit_at_1": 0.0,
                        "hit_at_3": 1.0,
                        "hit_at_5": 1.0,
                        "hit_at_10": 1.0,
                    }
                ],
            }
        ],
    }


class ReviewRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "review.db"
        self.generation_path = self.root / "generation.json"
        self.retrieval_path = self.root / "retrieval.json"
        self.generation_path.write_text(
            json.dumps(generation_report(), ensure_ascii=False), encoding="utf-8"
        )
        self.retrieval_path.write_text(
            json.dumps(retrieval_report(), ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_import_is_idempotent_and_covers_both_item_types(self) -> None:
        import_generation_report(self.generation_path, self.database)
        import_retrieval_report(self.retrieval_path, self.database)
        import_generation_report(self.generation_path, self.database)
        items = list_review_items(self.database)
        self.assertEqual(len(items), 2)
        self.assertEqual({item["item_type"] for item in items}, {"generation", "retrieval"})
        self.assertEqual(review_stats(self.database)["remaining_items"], 2)

    def test_existing_review_database_adds_stage5_rubric_columns(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute(
                """
                CREATE TABLE expert_reviews (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    question_verdict TEXT NOT NULL,
                    evidence_verdict TEXT NOT NULL,
                    answer_verdict TEXT NOT NULL,
                    refusal_verdict TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    error_categories_json TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    item_content_hash TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    UNIQUE (item_id, reviewer)
                )
                """
            )
            connection.commit()
        create_database(self.database)
        with closing(sqlite3.connect(self.database)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(expert_reviews)")
            }
            versions = {
                row[0] for row in connection.execute("SELECT version FROM schema_versions")
            }
        self.assertTrue(
            {"citation_verdict", "completeness_verdict", "reviewer_slot", "review_origin"}
            <= columns
        )
        self.assertIn(REVIEW_SCHEMA_VERSION, versions)

    def test_review_becomes_stale_when_system_output_changes(self) -> None:
        import_generation_report(self.generation_path, self.database)
        save_expert_review(
            item_id="generation:gen_001",
            reviewer="reviewer-01",
            question_verdict="valid",
            evidence_verdict="correct",
            answer_verdict="correct",
            refusal_verdict="not_applicable",
            severity="none",
            error_categories=[],
            notes="Evidence checked.",
            database_path=self.database,
        )
        self.generation_path.write_text(
            json.dumps(generation_report("- 靶点是 HER2，答案已更新。[S1]"), ensure_ascii=False),
            encoding="utf-8",
        )
        import_generation_report(self.generation_path, self.database)
        stale = list_review_items(self.database, status="stale")
        self.assertEqual(len(stale), 1)
        self.assertTrue(stale[0]["is_stale"])

    def test_generation_runs_are_isolated_and_keep_model_identity(self) -> None:
        first_path = self.root / "run_a.json"
        second_path = self.root / "run_b.json"
        first_path.write_text(
            json.dumps(generation_report(run_id="run-a"), ensure_ascii=False),
            encoding="utf-8",
        )
        second_path.write_text(
            json.dumps(
                generation_report(
                    "- 靶点是 HER2，来自第二次运行。[S1]",
                    run_id="run-b",
                    model="gpt-5-mini-2025-08-07",
                ),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        import_generation_report(first_path, self.database)
        import_generation_report(second_path, self.database)
        items = list_review_items(self.database, item_type="generation")
        self.assertEqual(len(items), 2)
        self.assertEqual(
            {item["evaluation_run_id"] for item in items}, {"run-a", "run-b"}
        )
        self.assertIn("generation:run-b:gen_001", {item["item_id"] for item in items})
        run_b = next(item for item in items if item["evaluation_run_id"] == "run-b")
        self.assertEqual(run_b["model_name"], "gpt-5-mini-2025-08-07")

    def test_review_export_writes_jsonl_csv_and_hash_manifest(self) -> None:
        import_generation_report(self.generation_path, self.database)
        save_expert_review(
            item_id="generation:gen_001",
            reviewer="reviewer-01",
            question_verdict="valid",
            evidence_verdict="correct",
            answer_verdict="correct",
            refusal_verdict="not_applicable",
            severity="none",
            error_categories=[],
            notes="Checked against source.",
            review_origin="human_independent",
            database_path=self.database,
        )
        jsonl_path = self.root / "reviews.jsonl"
        csv_path = self.root / "reviews.csv"
        manifest_path = self.root / "reviews_manifest.json"
        manifest = export_reviews(
            database_path=self.database,
            jsonl_path=jsonl_path,
            csv_path=csv_path,
            manifest_path=manifest_path,
        )
        exported = [
            json.loads(line)
            for line in jsonl_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(manifest["review_record_count"], 1)
        self.assertEqual(manifest["pending_item_count"], 0)
        self.assertEqual(exported[0]["review_status"], "reviewed")
        self.assertEqual(exported[0]["review_origin"], "human_independent")
        self.assertEqual(exported[0]["evaluation_run_id"], "legacy-generation-extractive")
        self.assertTrue(csv_path.read_text(encoding="utf-8-sig").startswith("answer_verdict"))
        self.assertEqual(len(manifest["files"]["jsonl"]["sha256"]), 64)

    def test_bad_case_report_separates_automatic_and_human_findings(self) -> None:
        import_generation_report(self.generation_path, self.database)
        save_expert_review(
            item_id="generation:gen_001",
            reviewer="reviewer-01",
            question_verdict="valid",
            evidence_verdict="partial",
            answer_verdict="partial",
            refusal_verdict="not_applicable",
            severity="medium",
            error_categories=["missing_key_fact"],
            notes="One requested fact is absent.",
            database_path=self.database,
        )
        report = build_bad_case_report(
            generation_report_path=self.generation_path,
            retrieval_report_path=self.retrieval_path,
            database_path=self.database,
        )
        self.assertEqual(report["summary"]["manual_review_count"], 1)
        self.assertEqual(report["summary"]["manual_bad_case_count"], 1)
        automatic_categories = {
            category
            for case in report["automatic_cases"]
            for category in case["categories"]
        }
        self.assertEqual(automatic_categories, {"missing_key_fact", "low_rank"})

    def test_bad_case_markdown_keeps_review_count_without_manual_cases(self) -> None:
        import_generation_report(self.generation_path, self.database)
        save_expert_review(
            item_id="generation:gen_001",
            reviewer="reviewer-01",
            question_verdict="valid",
            evidence_verdict="correct",
            answer_verdict="correct",
            refusal_verdict="not_applicable",
            severity="none",
            error_categories=[],
            notes="",
            database_path=self.database,
        )
        report = build_bad_case_report(
            generation_report_path=self.generation_path,
            retrieval_report_path=self.retrieval_path,
            database_path=self.database,
        )
        markdown = render_bad_case_markdown(report)
        self.assertEqual(report["summary"]["manual_review_count"], 1)
        self.assertEqual(report["summary"]["manual_bad_case_count"], 0)
        self.assertIn("已完成人工复核 1 条", markdown)
        self.assertNotIn("当前人工复核记录数为 0", markdown)


if __name__ == "__main__":
    unittest.main()
