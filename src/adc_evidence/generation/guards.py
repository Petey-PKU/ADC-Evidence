from __future__ import annotations

import re
from dataclasses import dataclass

from adc_evidence.processing.normalize import EntityNormalizer, normalize_text
from adc_evidence.rag.retriever import SearchResult


DOMAIN_TERMS = {
    "adc",
    "antibody drug conjugate",
    "抗体偶联药物",
    "抗体药物偶联物",
    "靶点",
    "抗体",
    "载荷",
    "payload",
    "linker",
    "连接子",
    "dar",
    "临床试验",
    "pubmed",
    "nct",
    "肿瘤",
    "癌",
    "her2",
    "trop2",
}

UNSAFE_PATTERNS = (
    "个体化剂量",
    "患者应该使用",
    "是否应该用",
    "替我诊断",
    "开处方",
    "调整用药",
    "personalized dose",
    "prescribe",
    "diagnose this patient",
)

FUTURE_PATTERNS = (
    "预测未来",
    "尚未公布",
    "未来一定",
    "2030年以后",
    "2035",
    "2040",
    "predict future",
    "not yet published",
)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str | None = None


class EvidenceGuard:
    def __init__(self) -> None:
        self.normalizer = EntityNormalizer()

    def check_question(self, question: str) -> GateDecision:
        stripped = question.strip()
        lowered = stripped.casefold()
        if not stripped:
            return GateDecision(False, "empty_question")
        if len(stripped) > 500:
            return GateDecision(False, "question_too_long")
        if any(pattern in lowered for pattern in UNSAFE_PATTERNS):
            return GateDecision(False, "personalized_medical_advice")
        if any(pattern in lowered for pattern in FUTURE_PATTERNS):
            return GateDecision(False, "future_or_unpublished_claim")
        has_entity = bool(self.normalizer.find_matches(stripped))
        has_domain_term = any(term in lowered for term in DOMAIN_TERMS)
        has_identifier = bool(re.search(r"\b(?:NCT\d{8}|PMID\s*:?\s*\d+)\b", stripped, re.I))
        if not (has_entity or has_domain_term or has_identifier):
            return GateDecision(False, "out_of_scope")
        return GateDecision(True)

    def check_evidence(
        self,
        question: str,
        results: list[SearchResult],
        mode: str,
    ) -> GateDecision:
        if not results:
            return GateDecision(False, "no_retrieval_results")
        minimum_score = {"sparse": 0.5, "dense": 0.20, "hybrid": 0.05}.get(mode, 0.0)
        if results[0].score < minimum_score:
            return GateDecision(False, "low_retrieval_relevance")

        combined = normalize_text(
            " ".join(
                f"{result.retrieval_document_id} {result.source_record_id} "
                f"{result.title} {result.content}"
                for result in results
            )
        )
        identifiers = re.findall(
            r"\b(?:NCT\d{8}|[A-Za-z]{2,}[- ]?\d{2,}[A-Za-z0-9-]*)\b",
            question,
            flags=re.IGNORECASE,
        )
        for identifier in identifiers:
            normalized_identifier = normalize_text(identifier)
            if normalized_identifier and normalized_identifier not in combined:
                return GateDecision(False, "specific_identifier_not_found")
        return GateDecision(True)
