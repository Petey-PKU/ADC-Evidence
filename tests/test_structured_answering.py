from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.database import connect
from adc_evidence.facts import FactObservationSet, ObservedFactValue, record_fact_sets
from adc_evidence.generation.citations import number_sources, validate_text_support
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.generation.models import AtomicClaim, GeneratorResponse
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.generation.structured import (
    route_question,
    validate_structured_claim,
)
from adc_evidence.rag.retriever import SearchResult
from adc_evidence.workbench import sync_public_seed_facts


def sample_result() -> SearchResult:
    return SearchResult(
        rank=1,
        chunk_id="adc_profile:adc_001#chunk-000",
        retrieval_document_id="adc_profile:adc_001",
        source_type="adc_profile",
        source_record_id="adc_001",
        title="ADC profile: Trastuzumab deruxtecan",
        content=(
            "ADC 名称 / ADC name: Trastuzumab deruxtecan\n"
            "别名 / aliases: T-DXd\n"
            "靶点 / target: HER2\n"
            "载荷 / payload: DXd\n"
            "药物抗体比 / DAR: 8.0"
        ),
        source_url="https://example.test/adc_001",
        score=10.0,
        metadata={"adc_ids": ["adc_001"]},
    )


class FakeRetriever:
    def __init__(self, results: list[SearchResult] | None = None) -> None:
        self.results = results if results is not None else [sample_result()]
        self.call_count = 0

    def search(self, question: str, **kwargs) -> list[SearchResult]:
        self.call_count += 1
        return self.results


class StaticGenerator:
    backend_name = "static"
    model_name = "static-test-v1"

    def __init__(self, text: str) -> None:
        self.text = text
        self.call_count = 0

    def generate(self, question, sources) -> GeneratorResponse:
        self.call_count += 1
        return GeneratorResponse(
            text=self.text,
            backend=self.backend_name,
            model=self.model_name,
        )


class StructuredAnsweringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary_directory.name) / "adc.db"
        sync_public_seed_facts(
            self.database,
            observed_at="2026-08-01T00:00:00+00:00",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _service(
        self,
        *,
        answer: str = "unused",
        results: list[SearchResult] | None = None,
    ) -> tuple[EvidenceAnsweringService, FakeRetriever, StaticGenerator]:
        retriever = FakeRetriever(results)
        generator = StaticGenerator(answer)
        return (
            EvidenceAnsweringService(
                database_path=self.database,
                retriever=retriever,
                generator=generator,
            ),
            retriever,
            generator,
        )

    def test_router_selects_all_six_policy_routes(self) -> None:
        cases = {
            "T-DXd 的 DAR 是多少？": "structured_fact",
            "比较 T-DXd 和 Trodelvy 的 payload": "comparison",
            "最近一周 ADC 有哪些变化？": "change_query",
            "NCT06394492 当前状态是什么？": "trial_lookup",
            "有哪些 T-DXd 耐药机制文献？": "literature_evidence",
            "一个未知 ADC 的估值是多少？": "refusal",
        }
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(route_question(self.database, question).route, expected)

    def test_router_prioritizes_trial_and_literature_intent(self) -> None:
        self.assertEqual(
            route_question(self.database, "T-DXd II 期研究的注册号和状态？").route,
            "trial_lookup",
        )
        self.assertEqual(
            route_question(self.database, "T-DXd 的活性和机制有哪些研究？").route,
            "literature_evidence",
        )
        self.assertEqual(
            route_question(self.database, "PMID 38164284 的 HER2 ADC 研究结论是什么？").route,
            "literature_evidence",
        )

    def test_router_accepts_source_collection_change_questions(self) -> None:
        self.assertEqual(
            route_question(self.database, "来源采集失败的变化事件有哪些？").route,
            "change_query",
        )

    def test_structured_fact_bypasses_retriever_and_generator(self) -> None:
        service, retriever, generator = self._service()
        result = service.answer("T-DXd 的靶点和 DAR 是多少？")

        self.assertEqual(result.status, "answered")
        self.assertEqual(result.route, "structured_fact")
        self.assertEqual(result.generator_backend, "structured")
        self.assertEqual({claim.predicate for claim in result.claims}, {"adc.target", "adc.dar"})
        self.assertTrue(result.claim_validation.valid)
        self.assertTrue(result.data_version["data_version"].startswith("data_"))
        self.assertEqual(retriever.call_count, 0)
        self.assertEqual(generator.call_count, 0)

    def test_missing_field_returns_explicit_partial_answer(self) -> None:
        service, _, _ = self._service()
        result = service.answer("SHR-A1921 的靶点和 DAR 是多少？")

        self.assertEqual(result.status, "partial")
        self.assertEqual([claim.predicate for claim in result.claims], ["adc.target"])
        self.assertEqual(result.unanswered[0].reason, "missing_direct_evidence")
        self.assertIn("未回答", result.answer)
        self.assertIn("DAR", result.answer)

    def test_conflicted_single_field_fails_closed(self) -> None:
        record_fact_sets(
            self.database,
            [
                FactObservationSet(
                    subject_type="adc",
                    subject_id="adc_001",
                    predicate="adc.dar",
                    values=[
                        ObservedFactValue(
                            value=7.0,
                            source_locator="fixture.dar",
                            evidence_text="DAR: 7.0",
                        )
                    ],
                    source="adcdb",
                    source_record_id="ADCDB001",
                    observed_at="2026-08-20T00:00:00+00:00",
                    source_url="https://example.test/adcdb/ADCDB001",
                    extractor="public_test_fixture_v1",
                )
            ],
        )
        service, _, _ = self._service()
        result = service.answer("T-DXd 的 DAR 是多少？")

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.route, "structured_fact")
        self.assertEqual(result.unanswered[0].reason, "conflicted")
        self.assertNotIn("8.0", result.answer)
        self.assertNotIn("7.0", result.answer)

    def test_comparison_is_cell_traceable_and_deterministic(self) -> None:
        service, retriever, generator = self._service()
        result = service.answer("比较 T-DXd 和 Trodelvy 的 payload")

        self.assertEqual(result.status, "answered")
        self.assertEqual(result.route, "comparison")
        self.assertEqual(len(result.claims), 2)
        self.assertEqual({claim.value[0] for claim in result.claims}, {"DXd", "SN-38"})
        self.assertEqual(len(result.citations), 2)
        self.assertEqual(retriever.call_count, 0)
        self.assertEqual(generator.call_count, 0)

    def test_trial_lookup_reads_standardized_registry_fields(self) -> None:
        with closing(connect(self.database)) as connection, connection:
            connection.execute(
                """
                INSERT INTO trials (
                    nct_id, brief_title, official_title, overall_status,
                    phases_json, conditions_json, interventions_json, sponsor,
                    enrollment, start_date, completion_date, last_update_date,
                    primary_outcomes_json, source_url, raw_path, checksum
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "NCT06394492",
                    "Public trial fixture",
                    None,
                    "RECRUITING",
                    '["PHASE2"]',
                    '["Breast Cancer"]',
                    '[{"name":"T-DXd","type":"DRUG"}]',
                    "Public sponsor",
                    120,
                    "2025-01",
                    "2027-01",
                    "2026-08-20",
                    '[{"measure":"ORR"}]',
                    "https://clinicaltrials.gov/study/NCT06394492",
                    "public-fixture.json",
                    "fixture-checksum",
                ),
            )
        service, retriever, generator = self._service()
        result = service.answer("NCT06394492 当前状态和阶段是什么？")

        self.assertEqual(result.status, "answered")
        self.assertEqual(result.route, "trial_lookup")
        self.assertEqual(
            {claim.predicate for claim in result.claims},
            {"trial.nct_id", "trial.overall_status", "trial.phases"},
        )
        self.assertIn("RECRUITING", result.answer)
        self.assertEqual(retriever.call_count, 0)
        self.assertEqual(generator.call_count, 0)

    def test_recent_change_query_uses_event_table(self) -> None:
        observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
        record_fact_sets(
            self.database,
            [
                FactObservationSet(
                    subject_type="adc",
                    subject_id="adc_001",
                    predicate="adc.development_status",
                    values=[
                        ObservedFactValue(
                            value="investigational",
                            source_locator="fixture.development_status",
                            evidence_text="development_status: investigational",
                        )
                    ],
                    source="curated_seed",
                    source_record_id="adc_001",
                    observed_at=observed_at,
                    source_url="https://example.test/adc_001",
                    extractor="public_test_fixture_v1",
                )
            ],
        )
        service, _, _ = self._service()
        result = service.answer("最近一天 T-DXd 有哪些变化？")

        self.assertEqual(result.status, "answered")
        self.assertEqual(result.route, "change_query")
        self.assertEqual(result.claims[0].predicate, "adc.development_status")
        self.assertIn("approved", result.answer)
        self.assertIn("investigational", result.answer)

    def test_structured_validator_rejects_value_not_in_field(self) -> None:
        claim = AtomicClaim(
            claim_id="C1",
            text="T-DXd 的 DAR 为 7.0。",
            subject_type="adc",
            subject_id="adc_001",
            predicate="adc.dar",
            value=[7.0],
            citation_ids=["S1"],
            support_kind="structured",
            validation_status="supported",
        )
        check = validate_structured_claim(
            claim,
            expected_value=[8.0],
            allowed_citation_ids=["S1"],
        )
        self.assertFalse(check.supported)
        self.assertEqual(check.reason, "value_not_equal_to_structured_field")

    def test_text_support_validator_checks_each_atomic_claim(self) -> None:
        answer = (
            "- T-DXd 的靶点是 HER2。[S1]\n"
            "- T-DXd 已获 FDA 批准用于肺癌。[S1]"
        )
        validation = validate_text_support(answer, number_sources([sample_result()]))

        self.assertFalse(validation.valid)
        self.assertEqual(validation.supported_claim_count, 1)
        self.assertEqual(validation.unsupported_claim_count, 1)

    def test_literature_partial_answer_hides_unsupported_claim(self) -> None:
        generated = (
            "- T-DXd 的靶点是 HER2。[S1]\n"
            "- T-DXd 已获 FDA 批准用于肺癌。[S1]"
        )
        service, _, _ = self._service(answer=generated)
        result = service.answer("有哪些 T-DXd 研究结论？")

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.route, "literature_evidence")
        self.assertEqual(len(result.claims), 1)
        self.assertIn("HER2", result.answer)
        self.assertNotIn("FDA", result.answer)
        self.assertNotIn("肺癌", result.answer)
        self.assertEqual(result.unanswered[0].reason, "validation_failed")

    def test_extractive_literature_answer_passes_direct_support_gate(self) -> None:
        retriever = FakeRetriever()
        service = EvidenceAnsweringService(
            database_path=self.database,
            retriever=retriever,
            generator=ExtractiveGenerator(),
        )
        result = service.answer("有哪些 T-DXd 研究结论？")

        self.assertEqual(result.status, "answered")
        self.assertEqual(result.route, "literature_evidence")
        self.assertTrue(result.claim_validation.valid)
        self.assertGreater(len(result.claims), 0)

    def test_literature_answer_with_no_supported_claim_is_refused(self) -> None:
        service, _, _ = self._service(
            answer="- T-DXd 已获 FDA 批准用于肺癌。[S1]"
        )
        result = service.answer("有哪些 T-DXd 研究结论？")

        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "text_support_validation_failed")
        self.assertNotIn("FDA", result.answer)
        self.assertNotIn("肺癌", result.answer)


if __name__ == "__main__":
    unittest.main()
