from __future__ import annotations

import re
import unicodedata
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
    "文献",
    "论文",
    "研究",
    "变化",
    "冲突",
    "来源",
    "记录",
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
    "患者应该停用",
    "患者应停用",
    "患者继续使用",
    "患者是否应该",
    "该不该停用",
    "personalized treatment",
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
    "目标价",
    "股价",
    "投资回报",
    "成功率",
    "预测",
)

PERSONAL_CONTEXT_PATTERNS = ("患者", "病人", "个人")
PERSONAL_ACTION_PATTERNS = ("停用", "继续使用", "换药", "调整用药", "治疗", "是否应该", "该不该")

# These intents require an explicit lexical anchor in the retrieved evidence.
# Without this small gate, a generally related abstract can pass citation and
# claim-term checks while still being irrelevant to the requested conclusion.
TOPIC_EVIDENCE_REQUIREMENTS = (
    (("旁观者效应", "bystander effect", "bystander"),),
    (("耐药逆转", "resistance reversal", "overcoming resistance"),),
    (("释放速率", "release rate", "release kinetics"),),
    (("最大耐受剂量", "maximum tolerated dose", "mtd"),),
    (("客观缓解率", "objective response rate", "orr"),),
    (("体内半衰期", "in vivo half-life", "half-life"),),
)


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    reason: str | None = None


class EvidenceGuard:
    def __init__(self, *, enforce_topic_alignment: bool = True) -> None:
        self.normalizer = EntityNormalizer()
        self.enforce_topic_alignment = enforce_topic_alignment

    def check_question(self, question: str) -> GateDecision:
        stripped = question.strip()
        lowered = stripped.casefold()
        if not stripped:
            return GateDecision(False, "empty_question")
        if len(stripped) > 500:
            return GateDecision(False, "question_too_long")
        if any(pattern in lowered for pattern in UNSAFE_PATTERNS):
            return GateDecision(False, "personalized_medical_advice")
        if any(context in lowered for context in PERSONAL_CONTEXT_PATTERNS) and any(
            action in lowered for action in PERSONAL_ACTION_PATTERNS
        ):
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
        explicit_pmids = re.findall(r"\bPMID\s*:?[ \t]*(\d+)\b", question, re.I)
        explicit_ncts = re.findall(r"\bNCT\d{8}\b", question, re.I)
        generic_identifiers = re.findall(
            r"\b(?!PMID\b)(?!NCT\d{8}\b)[A-Za-z]{2,}[- ]?\d{2,}[A-Za-z0-9-]*\b",
            question,
            flags=re.IGNORECASE,
        )
        identifiers = [*explicit_pmids, *explicit_ncts, *generic_identifiers]
        for identifier in identifiers:
            normalized_identifier = normalize_text(identifier)
            if normalized_identifier and normalized_identifier not in combined:
                return GateDecision(False, "specific_identifier_not_found")
        if self.enforce_topic_alignment:
            lowered_question = unicodedata.normalize("NFKC", question).casefold()
            lowered_evidence = unicodedata.normalize("NFKC", combined).casefold()
            for trigger_group in TOPIC_EVIDENCE_REQUIREMENTS:
                trigger = next(
                    (term for term in trigger_group[0] if term.casefold() in lowered_question),
                    None,
                )
                if trigger is None:
                    continue
                if not any(
                    term.casefold() in lowered_evidence
                    for term in trigger_group[0]
                ):
                    return GateDecision(False, "topic_not_supported")
        return GateDecision(True)
