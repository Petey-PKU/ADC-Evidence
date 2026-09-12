from __future__ import annotations
from tests.support import WorkspaceTemporaryDirectory

import json
import unittest
from pathlib import Path

from adc_evidence.config import BENCHMARK_REGRESSION_PATH
from adc_evidence.database import initialize_database
from adc_evidence.evaluation.benchmark import (
    CATEGORY_TARGETS,
    aggregate_human_scores,
    build_benchmark_bad_case_report,
    build_blinded_review_packet,
    build_external_arm_report,
    build_external_arm_request,
    build_regression_candidates,
    load_benchmark_questions,
    question_set_manifest,
    run_adc_evidence_arm,
    run_offline_rag_baseline,
    select_dev_pilot_questions,
    validate_arm_report,
)
from adc_evidence.evaluation.external_arms import run_siliconflow_external_arm
from adc_evidence.generation.models import (
    AnswerResult,
    AtomicClaim,
    CitationSource,
    CitationValidation,
)
from adc_evidence.rag.documents import build_retrieval_documents, chunk_documents, persist_retrieval_corpus
from adc_evidence.review.repository import (
    benchmark_reviews_from_database,
    import_benchmark_review_packet,
    list_review_items,
    save_expert_review,
)


def small_questions(*, double_review: bool = False) -> list[dict[str, object]]:
    return [
        {
            "question_id": "q1",
            "question": "T-DXd 的靶点是什么？",
            "split": "test",
            "category": "structured_fact",
            "expected_route": "structured_fact",
            "should_refuse": False,
            "expected_status": ["answered"],
            "expected_document_ids": ["adc_profile:adc_001"],
            "expected_adc_ids": ["adc_001"],
            "expected_predicates": ["target"],
            "required_terms": ["HER2"],
            "risk_level": "standard",
            "review_tier": "double" if double_review else "single",
            "second_review_required": double_review,
        }
    ]


def external_rows(answer: str) -> list[dict[str, object]]:
    return [{"question_id": "q1", "status": "answered", "answer": answer}]


def reports(questions: list[dict[str, object]]) -> list[dict[str, object]]:
    direct = build_external_arm_report(
        "direct_model",
        external_rows("HER2"),
        model="baseline-direct",
        evaluated_at="2026-08-21T01:00:00Z",
        evaluation_window_id="window-1",
        questions=questions,
        run_id="direct-1",
    )
    web = build_external_arm_report(
        "web_model",
        external_rows("HER2 with source"),
        model="baseline-web",
        evaluated_at="2026-08-21T01:01:00Z",
        evaluation_window_id="window-1",
        questions=questions,
        run_id="web-1",
    )
    adc = build_external_arm_report(
        "adc_evidence",
        [
            {
                "question_id": "q1",
                "status": "answered",
                "answer": "HER2",
                "claims": [
                    {
                        "claim_id": "claim-1",
                        "text": "T-DXd 的靶点是 HER2。",
                        "subject_type": "adc",
                        "subject_id": "adc_001",
                        "predicate": "target",
                        "value": "HER2",
                        "citation_ids": ["S1"],
                        "support_kind": "structured",
                        "validation_status": "supported",
                    }
                ],
                "citations": [
                    {
                        "citation_id": "S1",
                        "chunk_id": "chunk-1",
                        "retrieval_document_id": "adc_profile:adc_001",
                        "source_type": "adc_profile",
                        "title": "T-DXd",
                        "source_url": "https://example.test/adc_001",
                        "excerpt": "Target: HER2",
                    }
                ],
            }
        ],
        model="v0.6-structured-validator-v1",
        evaluated_at="2026-08-21T01:02:00Z",
        evaluation_window_id="window-1",
        questions=questions,
        run_id="adc-1",
    )
    return [direct, web, adc]


def verdict(candidate_id: str, slot: str = "primary", **changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "candidate_id": candidate_id,
        "reviewer_slot": slot,
        "review_origin": "human_adjudicated" if slot == "adjudicator" else "human_independent",
        "answer_verdict": "correct",
        "evidence_verdict": "correct",
        "citation_verdict": "correct",
        "completeness_verdict": "correct",
        "refusal_verdict": "not_applicable",
        "severity": "none",
        "error_categories": [],
    }
    row.update(changes)
    return row


class BenchmarkTests(unittest.TestCase):
    def test_offline_baseline_uses_same_window_and_never_networks(self) -> None:
        questions = small_questions()
        with WorkspaceTemporaryDirectory() as directory:
            database_path = Path(directory) / "baseline.db"
            initialize_database(database_path, Path(__file__).resolve().parents[1] / "data" / "sample" / "adcs.csv")
            documents = build_retrieval_documents(database_path)
            persist_retrieval_corpus(database_path, documents, chunk_documents(documents))
            report = run_offline_rag_baseline(
                database_path=database_path, questions=questions, evaluation_window_id="window-1"
            )
        self.assertEqual(report["arm"], "offline_rag_baseline")
        self.assertFalse(report["network_enabled"])
        self.assertEqual(report["question_count"], 1)
        self.assertEqual(report["evaluation_use"]["eligible_for_unseen_test_claim"], False)

    def test_frozen_question_set_has_exact_split_category_and_review_scope(self) -> None:
        questions = load_benchmark_questions()
        manifest = question_set_manifest(questions)
        self.assertEqual(manifest["question_count"], 120)
        self.assertEqual(manifest["split_counts"], {"dev": 40, "test": 80})
        self.assertEqual(manifest["category_counts"], dict(sorted(CATEGORY_TARGETS.items())))
        self.assertEqual(manifest["review_scope"]["double_review_question_count"], 45)
        self.assertEqual(manifest["review_scope"]["high_risk_double_review_count"], 20)
        self.assertTrue(str(manifest["question_set_hash"]).startswith("sha256:"))
        self.assertTrue(str(manifest["question_id_sha256"]).startswith("sha256:"))
        self.assertEqual(
            manifest["question_set_hash"],
            "sha256:ec3bb920f6eaa953ee55b38d436e8279ffe576be83b420d1c03d09a46a91c2da",
        )

    def test_public_regression_seed_is_deidentified_and_routable(self) -> None:
        rows = [
            json.loads(line)
            for line in BENCHMARK_REGRESSION_PATH.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(rows), 1)
        self.assertTrue(all(row.get("expected_route") for row in rows))
        public_text = json.dumps(rows)
        self.assertNotIn("reviewer", public_text.lower())
        self.assertNotIn("notes", public_text.lower())

    def test_external_request_separates_network_arms_and_hides_gold(self) -> None:
        questions = small_questions()
        direct = build_external_arm_request(
            "direct_model", questions=questions, evaluation_window_id="window-1"
        )
        web = build_external_arm_request(
            "web_model", questions=questions, evaluation_window_id="window-1"
        )
        self.assertFalse(direct["network_enabled"])
        self.assertTrue(web["network_enabled"])
        self.assertNotIn("expected_document_ids", direct["questions"][0])
        self.assertNotIn("required_terms", web["questions"][0])

    def test_dev_pilot_is_deterministic_and_never_uses_frozen_test_rows(self) -> None:
        first = select_dev_pilot_questions()
        second = select_dev_pilot_questions()
        self.assertEqual(first, second)
        self.assertEqual(len(first), 8)
        self.assertEqual({row["split"] for row in first}, {"dev"})
        category_counts = {
            category: sum(row["category"] == category for row in first)
            for category in {row["category"] for row in first}
        }
        self.assertEqual(set(category_counts.values()), {2})

    def test_external_runner_uses_same_model_with_and_without_search(self) -> None:
        class ModelClient:
            model_name = "deepseek-ai/DeepSeek-V4-Flash"

            def __init__(self) -> None:
                self.sources = []

            def answer(self, question, *, sources=None, accessed_at=None):
                self.sources.append(sources)
                return {
                    "status": "answered",
                    "answer": "T-DXd 的靶点是 HER2。[S1]" if sources else "HER2",
                    "usage": {"total_tokens": 10},
                    "response_id": "response-1",
                    "model": self.model_name,
                }

        class SearchClient:
            provider_name = "tavily-search-basic-v1"

            def search(self, query):
                return {
                    "results": [
                        {
                            "title": "Public source",
                            "url": "https://example.test/source",
                            "content": "T-DXd targets HER2.",
                        }
                    ],
                    "request_id": "search-1",
                    "credits": 1,
                    "estimated_credits": 1,
                }

        questions = small_questions()
        direct_client = ModelClient()
        direct = run_siliconflow_external_arm(
            "direct_model",
            questions=questions,
            evaluation_window_id="window-1",
            evaluated_at="2026-08-24T01:00:00Z",
            model_client=direct_client,
            run_id="direct-1",
        )
        web_client = ModelClient()
        web = run_siliconflow_external_arm(
            "web_model",
            questions=questions,
            evaluation_window_id="window-1",
            evaluated_at="2026-08-24T01:01:00Z",
            model_client=web_client,
            search_client=SearchClient(),
            run_id="web-1",
        )
        self.assertEqual(direct["model"], web["model"])
        self.assertEqual(direct_client.sources, [None])
        self.assertEqual(len(web_client.sources[0]), 1)
        self.assertEqual(web["questions"][0]["citations"][0]["citation_id"], "S1")
        self.assertEqual(web["questions"][0]["search_credits"], 1)
        self.assertEqual(web["questions"][0]["search_credit_estimate"], 1)
        self.assertNotIn("api_key", json.dumps(web).lower())

    def test_arm_validation_rejects_network_or_question_drift(self) -> None:
        questions = small_questions()
        report = reports(questions)[0]
        report["network_enabled"] = True
        with self.assertRaisesRegex(ValueError, "network_enabled"):
            validate_arm_report(report, questions)
        report["network_enabled"] = False
        report["questions"] = []
        with self.assertRaisesRegex(ValueError, "exactly one output"):
            validate_arm_report(report, questions)

    def test_system_arm_records_claims_citations_and_data_version(self) -> None:
        questions = small_questions()

        def answerer(question: str) -> AnswerResult:
            return AnswerResult(
                question=question,
                status="answered",
                answer="T-DXd 的靶点是 HER2。[S1]",
                generator_backend="structured",
                model="structured-v1",
                retrieval_mode="structured",
                route="structured_fact",
                citations=[
                    CitationSource(
                        citation_id="S1",
                        chunk_id="chunk-1",
                        retrieval_document_id="adc_profile:adc_001",
                        source_type="adc_profile",
                        title="T-DXd",
                        source_url="https://example.test/adc_001",
                        excerpt="Target: HER2",
                    )
                ],
                validation=CitationValidation(valid=True),
                claims=[
                    AtomicClaim(
                        claim_id="claim-1",
                        text="T-DXd 的靶点是 HER2。",
                        subject_type="adc",
                        subject_id="adc_001",
                        predicate="target",
                        value="HER2",
                        citation_ids=["S1"],
                        support_kind="structured",
                        validation_status="supported",
                    )
                ],
                data_version={"data_version": "sha256:sample"},
            )

        report = run_adc_evidence_arm(
            questions=questions,
            evaluation_window_id="window-1",
            evaluated_at="2026-08-21T01:02:00Z",
            answerer=answerer,
            run_id="adc-1",
        )
        row = report["questions"][0]
        self.assertEqual(row["claims"][0]["validation_status"], "supported")
        self.assertEqual(row["data_version"]["data_version"], "sha256:sample")
        self.assertTrue(row["output_hash"].startswith("sha256:"))

    def test_blind_mapping_is_deterministic_and_separate(self) -> None:
        questions = small_questions()
        packet_a, identity_a = build_blinded_review_packet(
            reports(questions), questions=questions, run_id="cmp-1"
        )
        packet_b, identity_b = build_blinded_review_packet(
            reports(questions), questions=questions, run_id="cmp-1"
        )
        self.assertEqual(packet_a, packet_b)
        self.assertEqual(identity_a, identity_b)
        packet_text = json.dumps(packet_a)
        self.assertNotIn("baseline-direct", packet_text)
        self.assertNotIn('"arm": "adc_evidence"', packet_text)
        self.assertIn("baseline-direct", json.dumps(identity_a))

    def test_double_review_requires_secondary_and_adjudication(self) -> None:
        questions = small_questions(double_review=True)
        packet, identity = build_blinded_review_packet(
            reports(questions), questions=questions, run_id="cmp-1"
        )
        reviews = []
        for candidate in packet["questions"][0]["candidates"]:
            reviews.append(verdict(candidate["candidate_id"], "primary"))
        summary = aggregate_human_scores(packet, identity, reviews)
        self.assertEqual(summary["status"], "awaiting_human_review")
        self.assertEqual(summary["review_coverage"]["required_review_coverage"], 0.5)

        for candidate in packet["questions"][0]["candidates"]:
            reviews.append(
                verdict(
                    candidate["candidate_id"],
                    "secondary",
                    answer_verdict=(
                        "incorrect" if candidate["blind_arm"] == "A" else "correct"
                    ),
                )
            )
        summary = aggregate_human_scores(packet, identity, reviews)
        self.assertEqual(summary["review_coverage"]["unresolved_disagreement_count"], 1)
        candidate_a = packet["questions"][0]["candidates"][0]["candidate_id"]
        reviews.append(verdict(candidate_a, "adjudicator", answer_verdict="partial"))
        summary = aggregate_human_scores(packet, identity, reviews)
        self.assertEqual(summary["status"], "complete")

    def test_benchmark_aggregation_rejects_nonhuman_review_origin(self) -> None:
        questions = small_questions()
        packet, identity = build_blinded_review_packet(
            reports(questions), questions=questions, run_id="cmp-1"
        )
        candidate_id = packet["questions"][0]["candidates"][0]["candidate_id"]
        with self.assertRaisesRegex(ValueError, "human_independent"):
            aggregate_human_scores(
                packet,
                identity,
                [verdict(candidate_id, review_origin="ai_assisted_primary")],
            )

    def test_human_bad_cases_and_regression_exclude_reviewer_identity(self) -> None:
        questions = small_questions()
        packet, identity = build_blinded_review_packet(
            reports(questions), questions=questions, run_id="cmp-1"
        )
        reviews = []
        adc_candidate = next(
            row
            for row in identity["mapping"]
            if row["arm"] == "adc_evidence"
        )["candidate_id"]
        for candidate in packet["questions"][0]["candidates"]:
            reviews.append(
                verdict(
                    candidate["candidate_id"],
                    answer_verdict=(
                        "partial"
                        if candidate["candidate_id"] == adc_candidate
                        else "correct"
                    ),
                    severity=(
                        "medium"
                        if candidate["candidate_id"] == adc_candidate
                        else "none"
                    ),
                    error_categories=(
                        ["missing_key_fact"]
                        if candidate["candidate_id"] == adc_candidate
                        else []
                    ),
                    reviewer="private-reviewer",
                    notes="private notes",
                )
            )
        bad_cases = build_benchmark_bad_case_report(packet, identity, reviews)
        regression = build_regression_candidates(
            packet, identity, reviews, questions=questions
        )
        self.assertEqual(bad_cases["summary"]["human_bad_case_count"], 1)
        self.assertEqual(len(regression), 1)
        self.assertEqual(regression[0]["regression_for"], "q1")
        public_text = json.dumps([bad_cases, regression])
        self.assertNotIn("private-reviewer", public_text)
        self.assertNotIn("private notes", public_text)

    def test_blind_packet_import_creates_answer_and_atomic_claim_items(self) -> None:
        questions = small_questions()
        packet, _ = build_blinded_review_packet(
            reports(questions), questions=questions, run_id="cmp-1"
        )
        with WorkspaceTemporaryDirectory() as temporary:
            root = Path(temporary)
            packet_path = root / "packet.json"
            database_path = root / "review.db"
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            counts = import_benchmark_review_packet(packet_path, database_path)
            self.assertEqual(counts, {"benchmark_answer": 3, "answer_claim": 3})
            items = list_review_items(database_path)
            self.assertEqual(len(items), 6)
            self.assertTrue(all(item["metadata"]["identity_hidden"] for item in items))
            self.assertTrue(all(item["model_name"] == "hidden-until-adjudication" for item in items))
            claim_items = [item for item in items if item["item_type"] == "answer_claim"]
            self.assertEqual({item["system_status"] for item in claim_items}, {"pending_human_review"})
            self.assertTrue(
                all(
                    "automatic_validation_status" not in item["metadata"]
                    for item in claim_items
                )
            )
            answer_item = next(item for item in items if item["item_type"] == "benchmark_answer")
            save_expert_review(
                item_id=answer_item["item_id"],
                reviewer="reviewer-01",
                reviewer_slot="primary",
                question_verdict="valid",
                evidence_verdict="correct",
                answer_verdict="correct",
                citation_verdict="correct",
                completeness_verdict="correct",
                refusal_verdict="not_applicable",
                severity="none",
                error_categories=[],
                notes="private",
                database_path=database_path,
            )
            exported = benchmark_reviews_from_database("cmp-1", database_path)
            self.assertEqual(len(exported), 1)
            self.assertNotIn("reviewer", exported[0])
            self.assertNotIn("notes", exported[0])


if __name__ == "__main__":
    unittest.main()
