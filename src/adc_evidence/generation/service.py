from __future__ import annotations

import re
import time
from pathlib import Path

from adc_evidence.generation.citations import (
    atomic_claim_lines,
    citation_sources,
    number_sources,
    validate_citations,
    validate_text_support,
)
from adc_evidence.generation.generators import AnswerGenerator, create_generator
from adc_evidence.generation.guards import EvidenceGuard
from adc_evidence.generation.models import (
    AnswerGap,
    AnswerResult,
    AtomicClaim,
    CitationValidation,
    ClaimValidationSummary,
    QuestionPlan,
)
from adc_evidence.generation.structured import (
    STRUCTURED_MODEL,
    StructuredAnswerEngine,
    route_question,
)
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.workbench import evidence_data_version


REFUSAL_MESSAGES = {
    "empty_question": "请输入一个具体问题。",
    "question_too_long": "问题过长，请缩小到一个可核查的事实。",
    "personalized_medical_advice": "本工具不提供个体化诊断、处方或剂量建议。",
    "future_or_unpublished_claim": "当前证据无法支持未来预测或尚未公布的结果。",
    "out_of_scope": "该问题不属于当前 ADC 证据库的范围。",
    "no_retrieval_results": "当前数据库中没有检索到相关证据。",
    "low_retrieval_relevance": "检索结果相关性不足，无法可靠作答。",
    "specific_identifier_not_found": "问题中的特定药物或试验编号未在证据中出现。",
    "topic_not_supported": "检索到的证据没有直接覆盖问题所问的具体结论。",
    "citation_validation_failed": "生成内容未通过引用完整性校验，因此不展示答案。",
    "text_support_validation_failed": "生成结论没有被所引证据片段直接支持，因此不展示答案。",
    "model_refusal": "现有证据不足以直接支持该问题。",
    "comparison_requires_two_known_adcs": "结构化比较需要识别至少两个已收录 ADC。",
    "no_supported_entity_or_route": "未识别到已收录实体或受支持的核查任务。",
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
        database_path: Path | None = None,
        seed_path: Path | None = None,
    ) -> None:
        if retriever is None:
            retriever = (
                HybridRetriever(database_path=database_path, seed_path=seed_path)
                if database_path is not None
                else HybridRetriever()
            )
        elif database_path is not None and isinstance(retriever, HybridRetriever):
            if retriever.database_path.resolve() != Path(database_path).resolve():
                raise ValueError("Structured queries and retrieval must use the same database")
        self.retriever = retriever
        self.generator = generator or create_generator("auto")
        self.guard = guard or EvidenceGuard()
        self.database_path = database_path
        self.structured = (
            StructuredAnswerEngine(database_path) if database_path is not None else None
        )

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
        route: str = "refusal",
        route_reason: str | None = None,
        claim_validation: ClaimValidationSummary | None = None,
        unanswered: list[AnswerGap] | None = None,
        data_version: dict[str, object] | None = None,
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
            route=route,
            route_reason=route_reason,
            retrieved_source_count=retrieved_source_count,
            claim_validation=claim_validation,
            unanswered=unanswered or [],
            data_version=data_version,
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

        plan: QuestionPlan | None = None
        version: dict[str, object] | None = None
        if self.database_path is not None:
            plan = route_question(self.database_path, question)
            version = evidence_data_version(self.database_path)
            if plan.route == "refusal":
                return self._refusal(
                    question,
                    plan.reason,
                    "none",
                    started_at,
                    route="refusal",
                    route_reason=plan.reason,
                    data_version=version,
                )
            if plan.route != "literature_evidence":
                try:
                    return self.structured.answer(
                        question,
                        plan,
                        started_at=started_at,
                    )
                except Exception as exc:
                    return AnswerResult(
                        question=question,
                        status="error",
                        answer="结构化查询发生错误；系统没有退回自由生成。",
                        refusal_reason=type(exc).__name__,
                        generator_backend="structured",
                        model=STRUCTURED_MODEL,
                        retrieval_mode="structured",
                        route=plan.route,
                        route_reason=plan.reason,
                        data_version=version,
                        latency_ms=round((time.perf_counter() - started_at) * 1000),
                    )

        try:
            source_type = (
                "pubmed"
                if plan is not None and plan.route == "literature_evidence"
                else infer_source_type(question)
            )
            identifier_search = getattr(self.retriever, "identifier_search", None)
            results = (
                identifier_search(
                    question,
                    source_type=source_type,
                    top_k=top_k,
                )
                if source_type in {"pubmed", "clinical_trial"}
                and callable(identifier_search)
                else []
            )
            if not results:
                # When a literature question names one ADC, constrain both
                # sparse and dense retrieval to documents linked to that
                # entity. This prevents generic ADC papers from displacing
                # directly relevant evidence in the fused top-k list.
                adc_filter = None
                if plan is not None and plan.route == "literature_evidence" and len(plan.adc_ids) == 1:
                    adc_filter = plan.adc_ids[0]
                topic_filter = None
                if plan is not None and plan.route == "literature_evidence":
                    lowered_question = question.casefold()
                    for topic, terms in {
                        "mechanism": ("机制", "mechanism", "内化", "旁观者"),
                        "efficacy": ("疗效", "efficacy", "缓解率", "生存"),
                        "safety": ("安全", "safety", "毒性", "不良事件"),
                    }.items():
                        if any(term.casefold() in lowered_question for term in terms):
                            topic_filter = topic
                            break
                results = self.retriever.search(
                    question,
                    mode=retrieval_mode,
                    top_k=top_k,
                    source_type=source_type,
                    adc_id=adc_filter,
                    topic=topic_filter,
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
                route="literature_evidence",
                route_reason=plan.reason if plan else "legacy_retrieval_route",
                data_version=version,
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
                route="literature_evidence",
                route_reason=plan.reason if plan else "legacy_retrieval_route",
                data_version=version,
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
                route="literature_evidence",
                route_reason=plan.reason if plan else "legacy_retrieval_route",
                retrieved_source_count=len(results),
                data_version=version,
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
                route="literature_evidence",
                route_reason=plan.reason if plan else "legacy_retrieval_route",
                data_version=version,
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
                route="literature_evidence",
                route_reason=plan.reason if plan else "legacy_retrieval_route",
                data_version=version,
            )
            result.validation = validation
            return result

        support_validation = validate_text_support(raw_answer, sources)
        lines = atomic_claim_lines(raw_answer)
        supported_lines: list[str] = []
        claims: list[AtomicClaim] = []
        unanswered: list[AnswerGap] = []
        supported_citation_ids: list[str] = []
        source_by_id = {source.citation_id: source for source in sources}
        for line, check in zip(lines, support_validation.claims, strict=True):
            if not check.supported:
                unanswered.append(
                    AnswerGap(
                        item=f"生成结论 {check.claim_id}",
                        reason="validation_failed",
                        detail="所引片段未包含该结论的全部可核查要素。",
                    )
                )
                continue
            supported_lines.append(f"- {line}")
            supported_citation_ids.extend(check.citation_ids)
            first_source = source_by_id[check.citation_ids[0]]
            claim_text = re.sub(r"\[[^\]]+\]", "", line).strip()
            claims.append(
                AtomicClaim(
                    claim_id=check.claim_id,
                    text=claim_text,
                    subject_type="publication",
                    subject_id=first_source.result.source_record_id,
                    predicate="publication.claim",
                    value=claim_text,
                    citation_ids=check.citation_ids,
                    support_kind="text",
                    validation_status="supported",
                )
            )

        if not claims:
            result = self._refusal(
                question,
                "text_support_validation_failed",
                retrieval_mode,
                started_at,
                retrieved_source_count=len(results),
                model=generated.model,
                usage=generated.usage,
                response_id=generated.response_id,
                route="literature_evidence",
                route_reason=plan.reason if plan else "legacy_retrieval_route",
                claim_validation=support_validation,
                unanswered=unanswered,
                data_version=version,
            )
            result.validation = validation
            return result

        if unanswered:
            supported_lines.extend(
                ["", "未回答："]
                + [f"- {gap.item}：{gap.detail}" for gap in unanswered]
            )
        citations = citation_sources(
            sources,
            list(dict.fromkeys(supported_citation_ids)),
        )
        return AnswerResult(
            question=question,
            status="partial" if unanswered else "answered",
            answer="\n".join(supported_lines),
            refusal_reason="partial_evidence" if unanswered else None,
            generator_backend=generated.backend,
            model=generated.model,
            retrieval_mode=retrieval_mode,
            route="literature_evidence",
            route_reason=plan.reason if plan else "legacy_retrieval_route",
            retrieved_source_count=len(results),
            citations=citations,
            validation=validation,
            claim_validation=support_validation,
            claims=claims,
            unanswered=unanswered,
            data_version=version,
            usage=generated.usage,
            response_id=generated.response_id,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )
