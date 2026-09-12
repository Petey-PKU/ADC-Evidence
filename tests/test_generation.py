from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from adc_evidence.generation.citations import number_sources, validate_citations
from adc_evidence.generation.generators import (
    ExtractiveGenerator,
    OpenAIResponsesGenerator,
    SiliconFlowChatGenerator,
    create_generator,
)
from adc_evidence.generation.guards import EvidenceGuard
from adc_evidence.generation.models import GeneratorResponse
from adc_evidence.generation.evaluate_generation import _aggregate_review_status
from adc_evidence.generation.prompts import build_generation_input, extract_requested_items
from adc_evidence.generation.service import EvidenceAnsweringService, infer_source_type
from adc_evidence.rag.retriever import SearchResult


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
        self.last_options: dict[str, object] = {}

    def search(self, question: str, **kwargs) -> list[SearchResult]:
        self.call_count += 1
        self.last_options = kwargs
        return self.results


class StaticGenerator:
    backend_name = "static"
    model_name = "static-test-v1"

    def __init__(self, text: str) -> None:
        self.text = text

    def generate(self, question, sources) -> GeneratorResponse:
        return GeneratorResponse(
            text=self.text,
            backend=self.backend_name,
            model=self.model_name,
        )


class CitationTests(unittest.TestCase):
    def test_valid_answer_requires_citation_on_every_claim(self) -> None:
        validation = validate_citations(
            "- 靶点是 HER2。[S1]\n- 载荷是 DXd。[S1]", {"S1"}
        )
        self.assertTrue(validation.valid)
        self.assertEqual(validation.coverage, 1.0)

    def test_unknown_citation_is_rejected(self) -> None:
        validation = validate_citations("- 靶点是 HER2。[S9]", {"S1"})
        self.assertFalse(validation.valid)
        self.assertEqual(validation.invalid_ids, ["S9"])

    def test_uncited_claim_is_rejected(self) -> None:
        validation = validate_citations("- 靶点是 HER2。", {"S1"})
        self.assertFalse(validation.valid)
        self.assertEqual(validation.coverage, 0.0)


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.guard = EvidenceGuard()

    def test_out_of_scope_question_is_refused(self) -> None:
        decision = self.guard.check_question("法国首都是什么？")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "out_of_scope")

    def test_personalized_medical_advice_is_refused(self) -> None:
        decision = self.guard.check_question("请推荐 T-DXd 个体化剂量")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "personalized_medical_advice")

    def test_missing_specific_identifier_is_refused(self) -> None:
        decision = self.guard.check_evidence(
            "ADC XYZ-999 的靶点是什么？", [sample_result()], "sparse"
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "specific_identifier_not_found")

    def test_pmid_label_is_not_treated_as_a_second_identifier(self) -> None:
        source = SearchResult(
            **{
                **sample_result().to_dict(),
                "source_type": "pubmed",
                "source_record_id": "34413126",
                "retrieval_document_id": "pubmed:34413126",
                "content": "Dato-DXd internalization and DXd release.",
            }
        )
        decision = self.guard.check_evidence(
            "PMID 34413126 的直接摘要证据是什么？",
            [source],
            "sparse",
        )
        self.assertTrue(decision.allowed)

    def test_precise_topic_without_evidence_is_refused(self) -> None:
        decision = self.guard.check_evidence(
            "文献摘要是否直接支持 Dato-DXd 具有旁观者效应？",
            [sample_result()],
            "sparse",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "topic_not_supported")

    def test_precise_topic_with_evidence_passes(self) -> None:
        result = SearchResult(
            **{
                **sample_result().to_dict(),
                "content": sample_result().content + "\nBystander effect was observed.",
            }
        )
        decision = self.guard.check_evidence(
            "文献摘要是否直接支持 Dato-DXd 具有旁观者效应？",
            [result],
            "sparse",
        )
        self.assertTrue(decision.allowed)

    def test_patient_action_is_refused(self) -> None:
        decision = self.guard.check_question("患者是否应该停用 T-DXd？")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "personalized_medical_advice")

    def test_forecast_and_investment_claim_is_refused(self) -> None:
        decision = self.guard.check_question("预测 SKB264 临床成功率和目标价")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "future_or_unpublished_claim")


class ServiceTests(unittest.TestCase):
    def test_valid_cited_answer_is_returned(self) -> None:
        service = EvidenceAnsweringService(
            retriever=FakeRetriever(),
            generator=StaticGenerator("- T-DXd 的靶点是 HER2。[S1]"),
        )
        result = service.answer("T-DXd 的靶点是什么？")
        self.assertEqual(result.status, "answered")
        self.assertEqual(result.citations[0].retrieval_document_id, "adc_profile:adc_001")

    def test_invalid_citation_causes_refusal(self) -> None:
        service = EvidenceAnsweringService(
            retriever=FakeRetriever(),
            generator=StaticGenerator("- T-DXd 的靶点是 HER2。[S8]"),
        )
        result = service.answer("T-DXd 的靶点是什么？")
        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "citation_validation_failed")

    def test_model_can_refuse_for_insufficient_evidence(self) -> None:
        service = EvidenceAnsweringService(
            retriever=FakeRetriever(),
            generator=StaticGenerator("REFUSE: 没有药代动力学证据。"),
        )
        result = service.answer("T-DXd 的半衰期是多少？")
        self.assertEqual(result.status, "refused")
        self.assertEqual(result.refusal_reason, "model_refusal")

    def test_guard_refusal_skips_retrieval(self) -> None:
        retriever = FakeRetriever()
        service = EvidenceAnsweringService(
            retriever=retriever,
            generator=StaticGenerator("unused"),
        )
        result = service.answer("法国首都是什么？")
        self.assertEqual(result.status, "refused")
        self.assertEqual(retriever.call_count, 0)

    def test_extractive_generator_produces_valid_citations(self) -> None:
        sources = number_sources([sample_result()])
        generated = ExtractiveGenerator().generate(
            "T-DXd 的靶点、载荷和 DAR 是什么？", sources
        )
        validation = validate_citations(generated.text, {"S1"})
        self.assertTrue(validation.valid)
        self.assertIn("HER2", generated.text)
        self.assertIn("DXd", generated.text)


class RoutingTests(unittest.TestCase):
    def test_routes_structured_and_source_specific_questions(self) -> None:
        self.assertEqual(infer_source_type("T-DXd 的 DAR 是多少？"), "adc_profile")
        self.assertEqual(infer_source_type("哪项 II 期试验的注册号？"), "clinical_trial")
        self.assertEqual(infer_source_type("哪篇 PubMed 文献？"), "pubmed")

    def test_auto_backend_honors_explicit_offline_preference(self) -> None:
        with patch.dict(
            os.environ,
            {"ADC_LLM_BACKEND": "extractive", "OPENAI_API_KEY": "test-key"},
            clear=True,
        ):
            self.assertIsInstance(create_generator("auto"), ExtractiveGenerator)

    def test_auto_backend_honors_siliconflow_preference(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ADC_LLM_BACKEND": "siliconflow",
                "SILICONFLOW_API_KEY": "test-key",
                "SILICONFLOW_MODEL": "deepseek-ai/DeepSeek-V4-Flash",
            },
            clear=True,
        ):
            generator = create_generator("auto")
            self.assertIsInstance(generator, SiliconFlowChatGenerator)
            self.assertEqual(generator.model_name, "deepseek-ai/DeepSeek-V4-Flash")

    def test_generation_question_review_status_is_propagated(self) -> None:
        reviewed = [{"review_status": "expert_reviewed"} for _ in range(2)]
        mixed = [
            {"review_status": "expert_reviewed"},
            {"review_status": "draft_domain_review"},
        ]
        self.assertEqual(_aggregate_review_status(reviewed), "expert_reviewed")
        self.assertEqual(_aggregate_review_status(mixed), "mixed")


class PromptTests(unittest.TestCase):
    def test_extracts_all_requested_fields_from_confirmed_bad_case(self) -> None:
        self.assertEqual(
            extract_requested_items(
                "Dato-DXd 的靶点、payload class 和研发状态是什么？"
            ),
            ["靶点 / target", "payload class / 载荷类型", "研发状态"],
        )

    def test_generation_input_contains_explicit_coverage_checklist(self) -> None:
        prompt = build_generation_input(
            "Dato-DXd 的靶点、payload class 和研发状态是什么？",
            number_sources([sample_result()]),
        )
        self.assertIn("<answer_requirements>", prompt)
        self.assertIn("- 靶点 / target", prompt)
        self.assertIn("- payload class / 载荷类型", prompt)
        self.assertIn("- 研发状态", prompt)
        self.assertIn("不得静默省略", prompt)


class OpenAIAdapterTests(unittest.TestCase):
    def test_uses_responses_api_without_network(self) -> None:
        class Usage:
            input_tokens = 100
            output_tokens = 20
            total_tokens = 120

        class Response:
            output_text = "- 靶点是 HER2。[S1]"
            usage = Usage()
            id = "resp_test"
            model = "gpt-5-mini-2025-08-07"

        class Responses:
            def __init__(self) -> None:
                self.arguments = None

            def create(self, **kwargs):
                self.arguments = kwargs
                return Response()

        class Client:
            def __init__(self) -> None:
                self.responses = Responses()

        generator = OpenAIResponsesGenerator(api_key="test-key", model_name="gpt-5-mini")
        client = Client()
        generator._client = client
        generated = generator.generate("T-DXd 的靶点是什么？", number_sources([sample_result()]))

        self.assertEqual(generated.text, "- 靶点是 HER2。[S1]")
        self.assertEqual(generated.usage["total_tokens"], 120)
        self.assertEqual(generated.model, "gpt-5-mini-2025-08-07")
        self.assertEqual(generated.response_id, "resp_test")
        self.assertEqual(client.responses.arguments["model"], "gpt-5-mini")
        self.assertFalse(client.responses.arguments["store"])
        self.assertIn("evidence_sources", client.responses.arguments["input"])


class SiliconFlowAdapterTests(unittest.TestCase):
    def test_uses_chat_completions_without_network(self) -> None:
        class Usage:
            prompt_tokens = 110
            completion_tokens = 25
            total_tokens = 135

        class Message:
            content = "- T-DXd 的靶点是 HER2。[S1]"

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]
            usage = Usage()
            id = "chatcmpl_test"
            model = "deepseek-ai/DeepSeek-V4-Flash"

        class Completions:
            def __init__(self) -> None:
                self.arguments = None

            def create(self, **kwargs):
                self.arguments = kwargs
                return Response()

        class Chat:
            def __init__(self) -> None:
                self.completions = Completions()

        class Client:
            def __init__(self) -> None:
                self.chat = Chat()

        generator = SiliconFlowChatGenerator(
            api_key="test-key",
            model_name="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1/",
        )
        client = Client()
        generator._client = client
        generated = generator.generate(
            "T-DXd 的靶点是什么？", number_sources([sample_result()])
        )

        arguments = client.chat.completions.arguments
        self.assertEqual(generated.text, "- T-DXd 的靶点是 HER2。[S1]")
        self.assertEqual(generated.backend, "siliconflow")
        self.assertEqual(generated.usage["input_tokens"], 110)
        self.assertEqual(generated.usage["output_tokens"], 25)
        self.assertEqual(generated.usage["total_tokens"], 135)
        self.assertEqual(generated.response_id, "chatcmpl_test")
        self.assertEqual(generator.base_url, "https://api.siliconflow.cn/v1")
        self.assertEqual(arguments["model"], "deepseek-ai/DeepSeek-V4-Flash")
        self.assertEqual(arguments["messages"][0]["role"], "system")
        self.assertEqual(arguments["messages"][1]["role"], "user")
        self.assertIn("evidence_sources", arguments["messages"][1]["content"])
        self.assertFalse(arguments["stream"])

    def test_empty_response_is_rejected(self) -> None:
        class Message:
            content = ""

        class Choice:
            message = Message()

        class Response:
            choices = [Choice()]

        class Completions:
            def create(self, **kwargs):
                return Response()

        class Chat:
            completions = Completions()

        class Client:
            chat = Chat()

        generator = SiliconFlowChatGenerator(
            api_key="test-key", model_name="deepseek-ai/DeepSeek-V4-Flash"
        )
        generator._client = Client()

        with self.assertRaisesRegex(RuntimeError, "empty answer"):
            generator.generate(
                "T-DXd 的靶点是什么？", number_sources([sample_result()])
            )


if __name__ == "__main__":
    unittest.main()
