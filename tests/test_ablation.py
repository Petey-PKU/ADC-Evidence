from __future__ import annotations
from tests.support import WorkspaceTemporaryDirectory

import unittest
from pathlib import Path

from adc_evidence.database import initialize_database
from adc_evidence.evaluation.ablation import run_identifier_routing_ablation
from adc_evidence.evaluation.holdout import load_holdout_questions
from adc_evidence.rag.documents import (
    build_retrieval_documents,
    chunk_documents,
    persist_retrieval_corpus,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class AblationTests(unittest.TestCase):
    def test_identifier_routing_ablation_records_two_arms(self) -> None:
        questions = load_holdout_questions(
            PROJECT_ROOT / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
        )[:2]
        with WorkspaceTemporaryDirectory() as tmp:
            database = Path(tmp) / "ablation.db"
            initialize_database(database, PROJECT_ROOT / "data" / "sample" / "adcs.csv")
            documents = build_retrieval_documents(database)
            persist_retrieval_corpus(database, documents, chunk_documents(documents))
            report = run_identifier_routing_ablation(
                database_path=database,
                questions=questions,
                evaluation_window_id="test-ablation",
            )
        self.assertEqual(set(report["arms"]), {"full_system", "without_identifier_routing"})
        self.assertEqual(report["question_count"], 2)
        self.assertFalse(report["network_enabled"])
        self.assertIn("paired_status_counts", report)
        self.assertIn("changed_question_ids", report)
        self.assertTrue(str(report["question_id_sha256"]).startswith("sha256:"))
        self.assertEqual(report["model"], "deterministic-extractive-v1")
        self.assertEqual(report["prompt_version"], "extractive-offline-v1")
        self.assertEqual(report["evaluation_conditions"]["candidate_limit"], 60)
        for arm in report["arms"].values():
            self.assertEqual(arm["prompt_version"], "extractive-offline-v1")
            self.assertEqual(arm["evaluation_conditions"]["retrieval_top_k"], 5)

        # This public smoke question is a structured fact.  A component
        # ablation must preserve the structured route in both arms.
        structured = next(
            row for row in questions if row.get("expected_route") == "structured_fact"
        )
        full_row = next(
            row for row in report["arms"]["full_system"]["questions"]
            if row["question_id"] == structured["question_id"]
        )
        ablation_row = next(
            row for row in report["arms"]["without_identifier_routing"]["questions"]
            if row["question_id"] == structured["question_id"]
        )
        self.assertEqual(full_row["route"], "structured_fact")
        self.assertEqual(ablation_row["route"], "structured_fact")

    def test_identifier_routing_ablation_rejects_empty_or_duplicate_questions(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            run_identifier_routing_ablation(
                database_path=PROJECT_ROOT / "data" / "processed" / "missing.db",
                questions=[],
                evaluation_window_id="test-ablation",
            )
        question = load_holdout_questions(
            PROJECT_ROOT / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
        )[0]
        duplicate = [dict(question), dict(question)]
        with self.assertRaisesRegex(ValueError, "unique question_id"):
            run_identifier_routing_ablation(
                database_path=PROJECT_ROOT / "data" / "processed" / "missing.db",
                questions=duplicate,
                evaluation_window_id="test-ablation",
            )


if __name__ == "__main__":
    unittest.main()
