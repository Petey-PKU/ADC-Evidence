import unittest
import hashlib
import json

from adc_evidence.evaluation.human_review import (
    question_id_sha256,
    summarize_human_paired_reviews,
    summarize_inter_rater_agreement,
)
from adc_evidence.evaluation.paper_readiness import (
    audit_public_paper_readiness,
    build_independent_holdout_manifest,
    build_human_review_manifest,
    validate_independent_holdout_file,
    validate_independent_holdout_manifest,
    validate_human_review_file,
    validate_human_review_manifest,
)
from pathlib import Path
from tests.support import WorkspaceTemporaryDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class HumanReviewTests(unittest.TestCase):
    def test_human_labels_produce_deterministic_paired_summary(self) -> None:
        rows = [
            {"question_id": "q1", "review_origin": "human_independent", "system_correct": True, "baseline_correct": False},
            {"question_id": "q2", "review_origin": "human_adjudicated", "system_correct": True, "baseline_correct": True},
        ]
        first = summarize_human_paired_reviews(rows, bootstrap_iterations=200, seed=7)
        second = summarize_human_paired_reviews(rows, bootstrap_iterations=200, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first["review_origin_counts"], {"human_adjudicated": 1, "human_independent": 1})
        self.assertEqual(first["question_count"], 2)
        self.assertTrue(str(first["question_id_sha256"]).startswith("sha256:"))
        self.assertTrue(first["human_review_required"])

    def test_ai_assisted_labels_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only human_independent"):
            summarize_human_paired_reviews(
                [{
                    "question_id": "q1",
                    "review_origin": "ai_assisted_primary",
                    "system_correct": True,
                    "baseline_correct": False,
                }]
            )

    def test_duplicate_question_ids_are_rejected(self) -> None:
        row = {"question_id": "q1", "review_origin": "human_independent", "system_correct": True, "baseline_correct": False}
        with self.assertRaisesRegex(ValueError, "Duplicate question_id"):
            summarize_human_paired_reviews([row, dict(row)])

    def test_inter_rater_agreement_is_computed_without_reviewer_identity(self) -> None:
        rows = [
            {"question_id": "q1", "reviewer_slot": "primary", "review_origin": "human_independent", "answer_verdict": "correct"},
            {"question_id": "q1", "reviewer_slot": "secondary", "review_origin": "human_independent", "answer_verdict": "correct"},
            {"question_id": "q2", "reviewer_slot": "primary", "review_origin": "human_independent", "answer_verdict": "partial"},
            {"question_id": "q2", "reviewer_slot": "secondary", "review_origin": "human_independent", "answer_verdict": "incorrect"},
        ]
        summary = summarize_inter_rater_agreement(rows)
        self.assertEqual(summary["question_count"], 2)
        self.assertEqual(summary["observed_agreement_rate"], 0.5)
        self.assertEqual(summary["disagreement_count"], 1)
        self.assertTrue(str(summary["question_id_sha256"]).startswith("sha256:"))
        self.assertNotIn("reviewer", " ".join(summary))

    def test_inter_rater_agreement_rejects_adjudicated_or_incomplete_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "human_independent"):
            summarize_inter_rater_agreement([
                {"question_id": "q1", "reviewer_slot": "primary", "review_origin": "human_adjudicated", "answer_verdict": "correct"},
                {"question_id": "q1", "reviewer_slot": "secondary", "review_origin": "human_independent", "answer_verdict": "correct"},
            ])

    def test_paper_readiness_audit_fails_closed_without_confirmation_artifacts(self) -> None:
        report = audit_public_paper_readiness(PROJECT_ROOT)
        self.assertEqual(report["status"], "not_ready_for_submission")
        self.assertEqual(report["blocker_count"], 2)
        self.assertEqual(report["warning_count"], 1)
        self.assertEqual(
            {item["name"] for item in report["checks"] if item["status"] == "blocker"},
            {"human_review_labels", "independent_holdout"},
        )

    def test_independent_holdout_manifest_requires_integrity_metadata(self) -> None:
        valid = {
            "question_set_version": "v1",
            "question_set_hash": "sha256:" + "a" * 64,
            "question_id_sha256": "sha256:" + "b" * 64,
            "question_file_sha256": "sha256:" + "c" * 64,
            "question_count": 40,
            "evaluation_window_id": "window-1",
            "access_controlled": True,
            "access_control_method": "private ACL",
            "access_control_attestation": "operator_asserted; verify independently before publication",
            "evaluation_use": {
                "status": "unseen_holdout",
                "eligible_for_unseen_test_claim": True,
            },
        }
        self.assertEqual(validate_independent_holdout_manifest(valid), valid)
        for field in (
            "question_set_hash",
            "question_id_sha256",
            "question_file_sha256",
            "question_count",
            "evaluation_window_id",
            "access_control_method",
            "access_control_attestation",
        ):
            invalid = dict(valid)
            invalid[field] = (
                "bad"
                if field == "question_set_hash"
                else 0
                if field == "question_count"
                else ""
            )
            with self.assertRaises(ValueError):
                validate_independent_holdout_manifest(invalid)

    def test_independent_holdout_file_binding_checks_hash_and_count(self) -> None:
        rows = [{
            "question_id": "q1",
            "question": "T-DXd 的靶点是什么？",
            "category": "structured_fact",
            "expected_route": "structured_fact",
            "expected_status": ["answered", "partial"],
            "standard_answer": {"kind": "structured", "field": "target", "value": "HER2"},
            "evidence_sources": [{"source_type": "fda", "source_record_id": "label-1", "source_url": "https://example.org/label", "field": "target"}],
            "allow_partial": False,
            "should_refuse": False,
            "scoring": {"primary_metric": "answer_field_accuracy", "automatic_fields": ["route"], "human_fields": ["answer_verdict"]},
        }]
        with WorkspaceTemporaryDirectory() as directory:
            questions_path = Path(directory) / "private_holdout.jsonl"
            questions_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            manifest = {
                "question_count": 1,
                "question_file_sha256": "sha256:" + hashlib.sha256(questions_path.read_bytes()).hexdigest(),
                "question_set_hash": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "question_id_sha256": question_id_sha256(str(row["question_id"]) for row in rows),
            }
            bound = validate_independent_holdout_file(questions_path, manifest)
            self.assertEqual(bound["question_count"], 1)
            self.assertEqual(bound["question_set_hash"], manifest["question_set_hash"])
            invalid = dict(manifest, question_file_sha256="sha256:" + "0" * 64)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_independent_holdout_file(questions_path, invalid)
            invalid_set = dict(manifest, question_set_hash="sha256:" + "0" * 64)
            with self.assertRaisesRegex(ValueError, "question set hash mismatch"):
                validate_independent_holdout_file(questions_path, invalid_set)
            invalid_ids = dict(manifest, question_id_sha256="sha256:" + "0" * 64)
            with self.assertRaisesRegex(ValueError, "question ID hash mismatch"):
                validate_independent_holdout_file(questions_path, invalid_ids)

    def test_independent_holdout_builder_rejects_question_without_gold_schema(self) -> None:
        with WorkspaceTemporaryDirectory() as directory:
            questions_path = Path(directory) / "incomplete.jsonl"
            questions_path.write_text(
                json.dumps({"question_id": "q1", "question": "T-DXd 的靶点是什么？"}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing fields"):
                build_independent_holdout_manifest(
                    questions_path,
                    question_set_version="holdout-v1",
                    evaluation_window_id="window-1",
                    access_control_method="private ACL",
                )

    def test_independent_holdout_manifest_builder_binds_external_file(self) -> None:
        rows = [
            {
                "question_id": "holdout-1", "question": "T-DXd 的靶点是什么？", "category": "structured_fact",
                "expected_route": "structured_fact", "expected_status": ["answered"],
                "standard_answer": {"kind": "structured", "field": "target", "value": "HER2"},
                "evidence_sources": [{"source_type": "fda", "source_record_id": "label-1", "source_url": "https://example.org/label", "field": "target"}],
                "allow_partial": False, "should_refuse": False,
                "scoring": {"primary_metric": "answer_field_accuracy", "automatic_fields": ["route"], "human_fields": ["answer_verdict"]},
            },
            {
                "question_id": "holdout-2", "question": "T-DM1 的载荷是什么？", "category": "structured_fact",
                "expected_route": "structured_fact", "expected_status": ["answered"],
                "standard_answer": {"kind": "structured", "field": "payload_name", "value": "DM1"},
                "evidence_sources": [{"source_type": "fda", "source_record_id": "label-2", "source_url": "https://example.org/label2", "field": "payload_name"}],
                "allow_partial": False, "should_refuse": False,
                "scoring": {"primary_metric": "answer_field_accuracy", "automatic_fields": ["route"], "human_fields": ["answer_verdict"]},
            },
        ]
        with WorkspaceTemporaryDirectory() as directory:
            questions_path = Path(directory) / "private_holdout.jsonl"
            questions_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            manifest = build_independent_holdout_manifest(
                questions_path,
                question_set_version="holdout-v1",
                evaluation_window_id="window-1",
                access_control_method="private ACL",
                database_data_version="data-v1",
                code_commit="abc123",
            )
            self.assertTrue(manifest["access_controlled"])
            self.assertEqual(validate_independent_holdout_manifest(manifest), manifest)
            bound = validate_independent_holdout_file(questions_path, manifest)
            self.assertEqual(bound["question_count"], 2)
            self.assertNotIn("private_holdout.jsonl", json.dumps(manifest))

    def test_readiness_does_not_pass_manifest_without_question_file(self) -> None:
        manifest = {
            "question_set_version": "v1",
            "question_set_hash": "sha256:" + "a" * 64,
            "question_id_sha256": "sha256:" + "b" * 64,
            "question_file_sha256": "sha256:" + "c" * 64,
            "question_count": 1,
            "evaluation_window_id": "window-1",
            "access_controlled": True,
            "access_control_method": "private ACL",
            "access_control_attestation": "operator_asserted; verify independently before publication",
            "evaluation_use": {
                "status": "unseen_holdout",
                "eligible_for_unseen_test_claim": True,
            },
        }
        with WorkspaceTemporaryDirectory() as directory:
            manifest_path = Path(directory) / "holdout_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = audit_public_paper_readiness(
                PROJECT_ROOT,
                independent_holdout_manifest=manifest_path,
            )
        holdout_check = next(
            item for item in report["checks"] if item["name"] == "independent_holdout"
        )
        self.assertEqual(holdout_check["status"], "blocker")

    def test_human_review_manifest_binds_file_and_question_set(self) -> None:
        rows = [
            {"question_id": "q1", "review_origin": "human_independent", "system_correct": True, "baseline_correct": False},
            {"question_id": "q2", "review_origin": "human_adjudicated", "system_correct": True, "baseline_correct": True},
        ]
        with WorkspaceTemporaryDirectory() as directory:
            reviews_path = Path(directory) / "reviews.jsonl"
            reviews_path.write_text(
                "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                encoding="utf-8",
            )
            manifest = {
                "review_file_sha256": "sha256:" + hashlib.sha256(reviews_path.read_bytes()).hexdigest(),
                "question_id_sha256": question_id_sha256(row["question_id"] for row in rows),
                "question_count": 2,
                "review_set_version": "v1",
                "evaluation_window_id": "window-1",
            }
            self.assertEqual(validate_human_review_manifest(manifest), manifest)
            bound = validate_human_review_file(reviews_path, manifest)
            self.assertEqual(bound["question_count"], 2)
            invalid = dict(manifest, review_file_sha256="sha256:" + "0" * 64)
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                validate_human_review_file(reviews_path, invalid)

    def test_human_review_manifest_builder_is_content_free_and_verifiable(self) -> None:
        rows = [
            {"question_id": "q1", "review_origin": "human_independent", "system_correct": True, "baseline_correct": False},
        ]
        with WorkspaceTemporaryDirectory() as directory:
            reviews_path = Path(directory) / "reviews.jsonl"
            reviews_path.write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
            manifest = build_human_review_manifest(
                reviews_path, review_set_version="v1", evaluation_window_id="window-1"
            )
            self.assertEqual(validate_human_review_file(reviews_path, manifest)["question_count"], 1)
            self.assertNotIn("system_correct", json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "exactly one primary"):
            summarize_inter_rater_agreement([
                {"question_id": "q1", "reviewer_slot": "primary", "review_origin": "human_independent", "answer_verdict": "correct"},
            ])
