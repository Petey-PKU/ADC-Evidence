from __future__ import annotations

import time

from adc_evidence.generation.citations import (
    citation_sources,
    number_sources,
    validate_citations,
)
from adc_evidence.generation.generators import AnswerGenerator, create_generator
from adc_evidence.generation.guards import EvidenceGuard
from adc_evidence.generation.models import AnswerResult, CitationValidation
from adc_evidence.rag.retriever import HybridRetriever


REFUSAL_MESSAGES = {
    "empty_question": "请输入一个具体问题。",
    "question_too_long": "问题过长，请缩小到一个可核查的事实。",
    "personalized_medical_advice": "本工具不提供个体化诊断、处方或剂量建议。",
    "future_or_unpublished_claim": "当前证据无法支持未来预测或尚未公布的结果。",
    "out_of_scope": "该问题不属于当前 ADC 证据库的范围。",
    "no_retrieval_results": "当前数据库中没有检索到相关证据。",
    "low_retrieval_relevance": "检索结果相关性不足，无法可靠作答。",
    "specific_identifier_not_found": "问题中的特定药物或试验编号未在证据中出现。",
    "citation_validation_failed": "生成内容未通过引用完整性校验，因此不展示答案。",
    "model_refusal": "现有证据不足以直接支持该问题。",
}


def infer_source_type(question: str) -> str | None:
    lowered = question.casefold()
    if any(
        marker in lowered
        for marker in ("临床试验", "注册号", "nct", "期试验", "招募状态", "已撤回")
    ):
        return "clinical_trial"
    if any(marker in lowered for marker in ("pubmed", "哪篇文献", "文章", "meta-analysis")):
        return "pubmed"
    if any(
        marker in lowered
        for marker in (
            "dar",
            "药物抗体比",
            "linker",
            "连接子",
            "研发状态",
            "开发企业",
            "公司",
        )
    ):
        return "adc_profile"
    return None


class EvidenceAnsweringService:
    def __init__(
        self,
        *,
        retriever: HybridRetriever | None = None,
        generator: AnswerGenerator | None = None,
        guard: EvidenceGuard | None = None,
    ) -> None:
        self.retriever = retriever or HybridRetriever()
        self.generator = generator or create_generator("auto")
        self.guard = guard or EvidenceGuard()

    def _refusal(
        self,
        question: str,
        reason: str,
        retrieval_mode: str,
        started_at: float,
        *,
        retrieved_source_count: int = 0,
        model_message: str | None = None,
        model: str | None = None,
        usage: dict[str, int] | None = None,
        response_id: str | None = None,
    ) -> AnswerResult:
        message = model_message or REFUSAL_MESSAGES.get(reason, "当前无法可靠回答。")
        return AnswerResult(
            question=question,
            status="refused",
            answer=message,
            refusal_reason=reason,
            generator_backend=self.generator.backend_name,
            model=model or self.generator.model_name,
            retrieval_mode=retrieval_mode,
            retrieved_source_count=retrieved_source_count,
            usage=usage or {},
            response_id=response_id,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )

    def answer(
        self,
        question: str,
        *,
        retrieval_mode: str = "sparse",
        top_k: int = 5,
    ) -> AnswerResult:
        started_at = time.perf_counter()
        question_decision = self.guard.check_question(question)
        if not question_decision.allowed:
            return self._refusal(
                question,
                str(question_decision.reason),
                retrieval_mode,
                started_at,
            )

        try:
            source_type = infer_source_type(question)
            results = self.retriever.search(
                question,
                mode=retrieval_mode,
                top_k=top_k,
                source_type=source_type,
            )
        except Exception as exc:
            return AnswerResult(
                question=question,
                status="error",
                answer="检索阶段发生错误，请检查索引和运行环境。",
                refusal_reason=type(exc).__name__,
                generator_backend=self.generator.backend_name,
                model=self.generator.model_name,
                retrieval_mode=retrieval_mode,
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )

        evidence_decision = self.guard.check_evidence(question, results, retrieval_mode)
        if not evidence_decision.allowed:
            return self._refusal(
                question,
                str(evidence_decision.reason),
                retrieval_mode,
                started_at,
                retrieved_source_count=len(results),
            )

        sources = number_sources(results, max_sources=top_k)
        try:
            generated = self.generator.generate(question, sources)
        except Exception as exc:
            return AnswerResult(
                question=question,
                status="error",
                answer="答案生成失败；检索结果没有丢失，请检查模型配置后重试。",
                refusal_reason=type(exc).__name__,
                generator_backend=self.generator.backend_name,
                model=self.generator.model_name,
                retrieval_mode=retrieval_mode,
                retrieved_source_count=len(results),
                latency_ms=round((time.perf_counter() - started_at) * 1000),
            )

        raw_answer = generated.text.strip()
        if raw_answer.upper().startswith("REFUSE:"):
            detail = raw_answer.split(":", 1)[1].strip() or None
            return self._refusal(
                question,
                "model_refusal",
                retrieval_mode,
                started_at,
                retrieved_source_count=len(results),
                model_message=detail,
                model=generated.model,
                usage=generated.usage,
                response_id=generated.response_id,
            )

        validation = validate_citations(
            raw_answer,
            {source.citation_id for source in sources},
        )
        if not validation.valid:
            result = self._refusal(
                question,
                "citation_validation_failed",
                retrieval_mode,
                started_at,
                retrieved_source_count=len(results),
                model=generated.model,
                usage=generated.usage,
                response_id=generated.response_id,
            )
            result.validation = validation
            return result

        citations = citation_sources(sources, validation.cited_ids)
        return AnswerResult(
            question=question,
            status="answered",
            answer=raw_answer,
            generator_backend=generated.backend,
            model=generated.model,
            retrieval_mode=retrieval_mode,
            retrieved_source_count=len(results),
            citations=citations,
            validation=validation,
            usage=generated.usage,
            response_id=generated.response_id,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
