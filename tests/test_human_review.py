import unittest

from adc_evidence.evaluation.human_review import (
    summarize_human_paired_reviews,
    summarize_inter_rater_agreement,
)


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
        self.assertNotIn("reviewer", " ".join(summary))

    def test_inter_rater_agreement_rejects_adjudicated_or_incomplete_pairs(self) -> None:
        with self.assertRaisesRegex(ValueError, "human_independent"):
            summarize_inter_rater_agreement([
                {"question_id": "q1", "reviewer_slot": "primary", "review_origin": "human_adjudicated", "answer_verdict": "correct"},
                {"question_id": "q1", "reviewer_slot": "secondary", "review_origin": "human_independent", "answer_verdict": "correct"},
            ])
        with self.assertRaisesRegex(ValueError, "exactly one primary"):
            summarize_inter_rater_agreement([
                {"question_id": "q1", "reviewer_slot": "primary", "review_origin": "human_independent", "answer_verdict": "correct"},
            ])
