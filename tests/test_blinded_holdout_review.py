from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.build_blinded_holdout_review import build_blinded_packet, validate_output_paths
from adc_evidence.evaluation.holdout import holdout_manifest
from tests.support import WorkspaceTemporaryDirectory


def _question(question_id: str = "h1") -> dict[str, object]:
    return {
        "question_id": question_id,
        "question": "Which linker is recorded?",
        "category": "structured_fact",
        "standard_answer": {"field": "linker_name", "value": "GGFG"},
        "evidence_sources": [
            {
                "source_type": "regulator_label",
                "source_record_id": "private-gold-id",
                "source_url": "https://example.test/label",
                "field": "adc.linker_name",
            }
        ],
    }


def _run(question_id: str = "h1") -> dict[str, object]:
    def row(arm: str) -> dict[str, object]:
        return {
            "question_id": question_id,
            "status": "answered",
            "route": "structured_fact",
            "answer": f"answer from {arm}",
            "claims": [{"text": f"claim from {arm}", "support_kind": "structured", "validation_status": "supported"}],
            "citations": [{"citation_id": "S1", "source_url": "https://example.test/label", "source_type": "structured_fact:curated_seed"}],
            "output_hash": f"sha256:{arm}",
        }

    return {
        "evaluation_window_id": "holdout-window",
        **holdout_manifest([{**_question(question_id), "split": "holdout", "evaluation_use": "public_smoke_holdout"}]),
        "arms": {
            "adc_evidence": {
                "model": "system-v1",
                "run_id": "system-run",
                "questions": [row("system")],
            },
            "offline_rag_baseline": {
                "model": "baseline-v1",
                "run_id": "baseline-run",
                "questions": [row("baseline")],
            },
        },
    }


class BlindedHoldoutReviewTests(unittest.TestCase):
    def test_packet_separates_gold_and_arm_identity(self) -> None:
        packet, identity, reviews = build_blinded_packet([_question()], _run())

        self.assertTrue(packet["blinded"])
        self.assertEqual(packet["question_count"], 1)
        self.assertEqual(packet["candidate_count"], 2)
        self.assertEqual(len(reviews), 4)
        self.assertEqual({row["reviewer_slot"] for row in reviews}, {"primary", "secondary"})
        packet_text = str(packet)
        self.assertNotIn("standard_answer", packet_text)
        self.assertNotIn("private-gold-id", packet_text)
        self.assertNotIn("adc_evidence", packet_text)
        self.assertNotIn("offline_rag_baseline", packet_text)
        self.assertEqual(
            {row["candidate_id"] for row in identity["mapping"]},
            {candidate["candidate_id"] for candidate in packet["questions"][0]["candidates"]},
        )
        self.assertEqual(identity["mapping_hash"], packet["mapping_hash"])
        self.assertTrue(all(row["review_origin"] is None for row in reviews))
        for key in ("route", "support_kind", "validation_status", "claim_support_valid", "output_hash", "blinding_key"):
            self.assertNotIn(key, packet_text)

    def test_rejects_stale_content_hash_and_duplicate_outputs(self) -> None:
        question = _question()
        question["question"] = "Changed wording with the same ID"
        with self.assertRaisesRegex(ValueError, "question_set_hash"):
            build_blinded_packet([question], _run())
        for field in ("question_id_sha256", "question_count"):
            run = _run()
            run[field] = None
            with self.assertRaisesRegex(ValueError, field):
                build_blinded_packet([_question()], run)
        run = _run()
        run["arms"]["adc_evidence"]["questions"] *= 2
        with self.assertRaisesRegex(ValueError, "exactly the frozen question IDs"):
            build_blinded_packet([_question()], run)

    def test_private_key_reproduces_assignment_without_disclosing_key(self) -> None:
        with patch("scripts.build_blinded_holdout_review.secrets.token_hex", return_value="12" * 32):
            first = build_blinded_packet([_question()], _run())
            replay = build_blinded_packet([_question()], _run())
        self.assertEqual(first, replay)
        self.assertEqual(first[1]["blinding_key"], "12" * 32)
        self.assertNotIn("12" * 32, str(first[0]))

    def test_path_guard_preserves_inputs_existing_reviews_and_public_boundary(self) -> None:
        with WorkspaceTemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "public"
            source = root / "questions.jsonl"
            source.write_text("original", encoding="utf-8")
            existing = root / "ratings.jsonl"
            existing.write_text("completed human rating", encoding="utf-8")
            for paths in ([source], [existing], [repo / "packet.json"], [root / "new", root / "new"]):
                with self.assertRaises(ValueError):
                    validate_output_paths([source], paths, repo)
            self.assertEqual(existing.read_text(encoding="utf-8"), "completed human rating")
            validate_output_paths([source], [root / "new-packet", root / "new-map"], repo)

    def test_packet_requires_exact_question_ids_for_both_arms(self) -> None:
        run = _run()
        run["arms"]["offline_rag_baseline"]["questions"] = []
        with self.assertRaisesRegex(ValueError, "exactly the frozen question IDs"):
            build_blinded_packet([_question()], run)

    def test_packet_requires_two_expected_arms(self) -> None:
        run = _run()
        del run["arms"]["offline_rag_baseline"]
        with self.assertRaisesRegex(ValueError, "exactly"):
            build_blinded_packet([_question()], run)


if __name__ == "__main__":
    unittest.main()
