from __future__ import annotations

import unittest

from adc_evidence.evaluation.benchmark import build_external_arm_report
from adc_evidence.evaluation.offline_comparison import compare_offline_reports
from adc_evidence.evaluation.statistics import holm_bonferroni_adjust, paired_binary_summary


def questions() -> list[dict[str, object]]:
    return [{
        "question_id": "q1", "question": "T-DXd 的靶点是什么？", "split": "test",
        "category": "structured_fact", "expected_route": "structured_fact", "should_refuse": False,
        "expected_status": ["answered"], "expected_document_ids": [], "expected_adc_ids": ["adc_001"],
        "expected_predicates": ["adc.target"], "required_terms": ["HER2"], "risk_level": "standard",
        "review_tier": "single", "second_review_required": False,
    }]


def report(arm: str, status: str, route: str) -> dict[str, object]:
    rows = questions()
    result = build_external_arm_report(
        arm, [{"question_id": "q1", "status": status, "answer": "synthetic", "route": route}],
        model="test", evaluated_at="2026-09-12T00:00:00Z", evaluation_window_id="window",
        questions=rows,
    )
    result["database_data_version"] = {"data_version": "test-db-v1"}
    return result


class OfflineComparisonTests(unittest.TestCase):
    def test_paired_summary_is_split_and_status_aware(self) -> None:
        system = report("adc_evidence", "answered", "structured_fact")
        baseline = report("offline_rag_baseline", "refused", "literature_evidence")
        summary = compare_offline_reports(system, baseline, questions())
        self.assertEqual(summary["question_count"], 1)
        self.assertEqual(summary["paired_status_counts"], {"answered->refused": 1})
        self.assertEqual(summary["paired_route_counts"], {"structured_fact->literature_evidence": 1})
        self.assertEqual(summary["by_category"]["structured_fact"]["system_expected_status_match_rate"], 1.0)
        self.assertEqual(summary["by_category"]["structured_fact"]["baseline_expected_status_match_rate"], 0.0)

    def test_window_or_arm_mismatch_fails_closed(self) -> None:
        system = report("adc_evidence", "answered", "structured_fact")
        baseline = report("offline_rag_baseline", "refused", "literature_evidence")
        baseline["evaluation_window_id"] = "different"
        with self.assertRaises(ValueError):
            compare_offline_reports(system, baseline, questions())

    def test_question_id_binding_mismatch_fails_closed(self) -> None:
        system = report("adc_evidence", "answered", "structured_fact")
        baseline = report("offline_rag_baseline", "refused", "literature_evidence")
        baseline["question_id_sha256"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "question ID binding"):
            compare_offline_reports(system, baseline, questions())

    def test_database_version_mismatch_fails_closed(self) -> None:
        system = report("adc_evidence", "answered", "structured_fact")
        baseline = report("offline_rag_baseline", "refused", "literature_evidence")
        baseline["database_data_version"] = {"data_version": "different-db"}
        with self.assertRaises(ValueError):
            compare_offline_reports(system, baseline, questions())

    def test_paired_binary_summary_is_deterministic_and_pair_aware(self) -> None:
        system = [True, True, False, True, False]
        baseline = [True, False, False, True, True]
        first = paired_binary_summary(system, baseline, bootstrap_iterations=500, seed=7)
        second = paired_binary_summary(system, baseline, bootstrap_iterations=500, seed=7)

        self.assertEqual(first, second)
        self.assertEqual(first["system_success_count"], 3)
        self.assertEqual(first["baseline_success_count"], 3)
        self.assertEqual(first["system_only_discordant"], 1)
        self.assertEqual(first["baseline_only_discordant"], 1)
        self.assertEqual(first["mcnemar_exact_two_sided_pvalue"], 1.0)

    def test_paired_binary_summary_rejects_unpaired_input(self) -> None:
        with self.assertRaises(ValueError):
            paired_binary_summary([True], [True, False])

    def test_holm_adjustment_is_order_preserving_and_step_down(self) -> None:
        self.assertEqual(
            holm_bonferroni_adjust([0.04, 0.01, 0.2]),
            [0.08, 0.03, 0.2],
        )
        with self.assertRaises(ValueError):
            holm_bonferroni_adjust([0.1, 1.1])


if __name__ == "__main__":
    unittest.main()
