from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from adc_evidence.database import initialize_database
from adc_evidence.evaluation.holdout import (
    HOLDOUT_VERSION,
    holdout_manifest,
    load_holdout_questions,
    run_public_holdout,
    validate_holdout_disjoint,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PublicHoldoutTests(unittest.TestCase):
    def test_holdout_manifest_is_unseen_and_hashed(self) -> None:
        path = PROJECT_ROOT / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
        questions = load_holdout_questions(path)
        manifest = holdout_manifest(questions)
        self.assertEqual(manifest["question_set_version"], HOLDOUT_VERSION)
        self.assertEqual(manifest["evaluation_use"]["status"], "unseen_holdout")
        self.assertTrue(manifest["evaluation_use"]["eligible_for_unseen_test_claim"])
        self.assertTrue(str(manifest["question_set_hash"]).startswith("sha256:"))

    def test_holdout_rejects_duplicate_question_text(self) -> None:
        holdout = [{"question_id": "h1", "question": "T-DXd 的靶点是什么？"}]
        exposed = [{"question_id": "e1", "question": "T-DXd 的靶点是什么？"}]
        with self.assertRaises(ValueError):
            validate_holdout_disjoint(holdout, exposed)

    def test_holdout_disjoint_check_returns_audit_record(self) -> None:
        result = validate_holdout_disjoint(
            [{"question_id": "h1", "question": "T-DXd 的 payload 是什么？"}],
            [{"question_id": "e1", "question": "T-DXd 的 DAR 是多少？"}],
        )
        self.assertEqual(result["status"], "disjoint")
        self.assertEqual(result["overlap_count"], 0)

    def test_holdout_runs_both_local_arms_without_network(self) -> None:
        path = PROJECT_ROOT / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
        questions = load_holdout_questions(path)
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "holdout.db"
            initialize_database(database, PROJECT_ROOT / "data" / "sample" / "adcs.csv")
            from adc_evidence.rag.documents import build_retrieval_documents, chunk_documents, persist_retrieval_corpus

            documents = build_retrieval_documents(database)
            persist_retrieval_corpus(database, documents, chunk_documents(documents))
            report = run_public_holdout(
                database_path=database,
                questions=questions,
                evaluation_window_id="test-holdout",
            )
        self.assertEqual(report["question_count"], 20)
        self.assertEqual(report["evaluation_use"]["status"], "unseen_holdout")
        self.assertEqual(set(report["arms"]), {"adc_evidence", "offline_rag_baseline"})
        for arm in report["arms"].values():
            self.assertFalse(arm["network_enabled"])
            self.assertEqual(len(arm["questions"]), 20)


if __name__ == "__main__":
    unittest.main()
