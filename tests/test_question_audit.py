from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from adc_evidence.evaluation.benchmark import (
    load_benchmark_questions,
    question_set_manifest,
    run_adc_evidence_arm,
)
from adc_evidence.evaluation.question_audit import audit_system_report, inspect_question_file
from adc_evidence.generation.models import AnswerResult


class QuestionFileAuditTests(unittest.TestCase):
    def _inspect(self, raw: bytes) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.jsonl"
            path.write_bytes(raw)
            return inspect_question_file(path)

    def test_valid_chinese_is_not_terminal_encoding_damage(self) -> None:
        raw = json.dumps({"question_id": "q", "question": "两种药物有何不同？"}, ensure_ascii=False).encode("utf-8")
        result = self._inspect(raw)
        self.assertTrue(result["valid"])
        self.assertEqual(result["row_count"], 1)

    def test_invalid_utf8_and_escaped_damage_are_rejected(self) -> None:
        bad_rows = [b'\xff', b'{invalid json}', b'[]', b'']
        for text in ("ADC \ufffd", "ADC \ud800", "ADC \x00", " "):
            bad_rows.append(json.dumps({"question_id": "q", "question": text}).encode("ascii"))
        for raw in bad_rows:
            with self.subTest(raw=raw):
                self.assertFalse(self._inspect(raw)["valid"])

    def test_duplicate_ids_fail_file_audit(self) -> None:
        row = b'{"question_id":"q","question":"ADC?"}\n'
        result = self._inspect(row + row)
        self.assertFalse(result["valid"])
        self.assertIn("duplicate_question_id", [item["reason"] for item in result["issues"]])

    def test_loader_rejects_damaged_question_before_running(self) -> None:
        from adc_evidence.evaluation.benchmark import _read_jsonl

        def damaged_rows(path):
            rows = _read_jsonl(path)
            rows[0]["question"] = "ADC \ufffd"
            return rows

        with patch("adc_evidence.evaluation.benchmark._read_jsonl", side_effect=damaged_rows):
            with self.assertRaisesRegex(ValueError, "Invalid question text"):
                load_benchmark_questions()


class SystemReportAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        # Two public questions exercise the real legacy ID normalization and split join.
        all_questions = load_benchmark_questions()
        self.questions = [all_questions[0], next(q for q in all_questions if q["split"] == "test")]
        self.report = run_adc_evidence_arm(
            questions=self.questions,
            evaluation_window_id="synthetic-audit-test",
            answerer=lambda question: AnswerResult(
                question=question, status="refused", answer="Synthetic answer; not a medical judgment.",
                route="refusal", generator_backend="test", model="test", retrieval_mode="none",
            ),
        )

    def test_all_mismatches_include_legacy_dev_and_test_ids(self) -> None:
        audit = audit_system_report(self.report, self.questions)
        self.assertEqual(audit["route_mismatch_count"], 2)
        for split in ("dev", "test"):
            self.assertEqual(audit["by_split"][split]["route_mismatch_count"], 1)
        self.assertEqual({row["question_id"] for row in audit["mismatches"]}, {q["question_id"] for q in self.questions})
        self.assertNotIn("Synthetic answer", json.dumps(audit))

    def test_missing_routes_count_as_mismatches_not_disappearing_denominators(self) -> None:
        self.report["questions"][0]["route"] = None
        self.report["automatic_diagnostics"]["route_match_rate"] = 1.0
        audit = audit_system_report(self.report, self.questions)
        self.assertEqual(audit["by_split"]["dev"]["route_match_rate"], 0)
        self.assertEqual(audit["by_split"]["dev"]["route_missing_count"], 1)
        self.assertFalse(audit["stored_diagnostics_match"])

    def test_wrong_hash_missing_and_duplicate_outputs_fail(self) -> None:
        bad_reports = [copy.deepcopy(self.report) for _ in range(3)]
        bad_reports[0]["question_set_hash"] = "sha256:wrong"
        bad_reports[1]["questions"].pop()
        bad_reports[2]["questions"][1] = bad_reports[2]["questions"][0]
        for report in bad_reports:
            with self.assertRaises(ValueError):
                audit_system_report(report, self.questions)

    def test_manifest_preserves_original_freeze_and_discloses_exposure(self) -> None:
        manifest = question_set_manifest()
        self.assertEqual(manifest["implementation_frozen_after"], "v0.6-structured-validator-v1")
        self.assertEqual(manifest["current_implementation"], "v0.6-structured-validator-v4")
        self.assertFalse(manifest["evaluation_use"]["eligible_for_unseen_test_claim"])
        self.assertFalse(self.report["evaluation_use"]["eligible_for_unseen_test_claim"])


if __name__ == "__main__":
    unittest.main()
