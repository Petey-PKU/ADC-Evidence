from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from adc_evidence.generation.models import (
    CitationSource,
    CitationValidation,
    ClaimSupport,
    ClaimValidationSummary,
)
from adc_evidence.rag.retriever import SearchResult


@dataclass(frozen=True)
class NumberedSource:
    citation_id: str
    result: SearchResult
    excerpt: str


def number_sources(
    results: list[SearchResult],
    *,
    max_sources: int = 5,
    max_chars_per_source: int = 1400,
    max_total_chars: int = 7000,
) -> list[NumberedSource]:
    numbered: list[NumberedSource] = []
    used_chars = 0
    for result in results[:max_sources]:
        remaining = max_total_chars - used_chars
        if remaining <= 0:
            break
        excerpt = result.content[: min(max_chars_per_source, remaining)].strip()
        if not excerpt:
            continue
        numbered.append(
            NumberedSource(
                citation_id=f"S{len(numbered) + 1}",
                result=result,
                excerpt=excerpt,
            )
        )
        used_chars += len(excerpt)
    return numbered


def format_context(sources: list[NumberedSource]) -> str:
    sections = []
    for source in sources:
        result = source.result
        sections.append(
            "\n".join(
                (
                    f"[{source.citation_id}]",
                    f"title: {result.title}",
                    f"source_type: {result.source_type}",
                    f"document_id: {result.retrieval_document_id}",
                    f"url: {result.source_url}",
                    "content:",
                    source.excerpt,
                )
            )
        )
    return "\n\n".join(sections)


def extract_citation_ids(answer: str) -> list[str]:
    found: list[str] = []
    for group in re.findall(r"\[([^\]]+)\]", answer):
        for number in re.findall(r"\bS(\d+)\b", group, flags=re.IGNORECASE):
            citation_id = f"S{int(number)}"
            if citation_id not in found:
                found.append(citation_id)
    return found


def atomic_claim_lines(answer: str) -> list[str]:
    ignored_headings = {"答案", "回答", "依据", "结论", "answer", "evidence"}
    claims: list[str] = []
    for raw_line in answer.splitlines():
        line = raw_line.strip().lstrip("-*•0123456789.、 ").strip()
        if not line or line.rstrip("：:").casefold() in ignored_headings:
            continue
        if line.startswith("#") or line.upper().startswith("REFUSE:"):
            continue
        if len(re.sub(r"\[[^\]]+\]", "", line).strip()) >= 6:
            claims.append(line)
    return claims


def validate_citations(answer: str, available_ids: set[str]) -> CitationValidation:
    cited_ids = extract_citation_ids(answer)
    invalid_ids = [citation_id for citation_id in cited_ids if citation_id not in available_ids]
    claims = atomic_claim_lines(answer)
    cited_claim_count = sum(bool(extract_citation_ids(claim)) for claim in claims)
    coverage = cited_claim_count / len(claims) if claims else 0.0
    valid = bool(cited_ids) and not invalid_ids and bool(claims) and coverage == 1.0
    return CitationValidation(
        valid=valid,
        cited_ids=cited_ids,
        invalid_ids=invalid_ids,
        claim_count=len(claims),
        cited_claim_count=cited_claim_count,
        coverage=round(coverage, 4),
    )


_SUPPORT_NOISE = {
    "adc",
    "answer",
    "evidence",
    "pubmed",
    "结论",
    "文献",
    "研究",
    "结果",
    "证据",
    "证据摘录",
    "摘录",
    "根据",
    "报道",
}

_CHINESE_CONNECTORS = (
    "的数据表明",
    "的研究显示",
    "研究表明",
    "研究显示",
    "证据显示",
    "证据表明",
    "可能",
    "提示",
    "发现",
    "显示",
    "表明",
    "认为",
    "以及",
    "其中",
    "用于",
    "关于",
    "相关",
    "分别",
    "当前",
    "已经",
    "可以",
    "为",
    "是",
    "的",
    "与",
    "及",
    "和",
    "在",
    "中",
)


def _support_terms(text: str) -> list[str]:
    cleaned = re.sub(r"\[[^\]]+\]", " ", text)
    cleaned = cleaned.strip().lstrip("-*•0123456789.、 ")
    normalized = unicodedata.normalize("NFKC", cleaned).casefold()
    for connector in _CHINESE_CONNECTORS:
        normalized = normalized.replace(connector, " ")
    tokens = re.findall(
        r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*|\d+(?:\.\d+)?|[\u4e00-\u9fff]{2,}",
        normalized,
    )
    terms: list[str] = []
    for token in tokens:
        token = token.strip("-")
        if token in _SUPPORT_NOISE or len(token) < 2:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def validate_text_support(
    answer: str,
    sources: list[NumberedSource],
) -> ClaimValidationSummary:
    """Fail closed unless every material claim term occurs in its cited excerpts."""
    source_map = {source.citation_id: source for source in sources}
    checks: list[ClaimSupport] = []
    for index, claim in enumerate(atomic_claim_lines(answer), start=1):
        citation_ids = extract_citation_ids(claim)
        cited_text = " ".join(
            source_map[citation_id].excerpt
            for citation_id in citation_ids
            if citation_id in source_map
        )
        normalized_evidence = unicodedata.normalize("NFKC", cited_text).casefold()
        terms = _support_terms(claim)
        matched = [term for term in terms if term in normalized_evidence]
        missing = [term for term in terms if term not in normalized_evidence]
        if not citation_ids:
            reason = "missing_citation"
        elif any(citation_id not in source_map for citation_id in citation_ids):
            reason = "unknown_citation"
        elif not terms:
            reason = "no_verifiable_terms"
        elif missing:
            reason = "terms_not_in_cited_evidence"
        else:
            reason = None
        checks.append(
            ClaimSupport(
                claim_id=f"C{index}",
                supported=reason is None,
                citation_ids=citation_ids,
                matched_terms=matched,
                missing_terms=missing,
                reason=reason,
            )
        )
    supported = sum(check.supported for check in checks)
    return ClaimValidationSummary(
        valid=bool(checks) and supported == len(checks),
        support_kind="text",
        claim_count=len(checks),
        supported_claim_count=supported,
        unsupported_claim_count=len(checks) - supported,
        claims=checks,
    )


def citation_sources(
    sources: list[NumberedSource], cited_ids: list[str]
) -> list[CitationSource]:
    by_id = {source.citation_id: source for source in sources}
    citations: list[CitationSource] = []
    for citation_id in cited_ids:
        source = by_id.get(citation_id)
        if source is None:
            continue
        result = source.result
        citations.append(
            CitationSource(
                citation_id=citation_id,
                chunk_id=result.chunk_id,
                retrieval_document_id=result.retrieval_document_id,
                source_type=result.source_type,
                title=result.title,
                source_url=result.source_url,
                excerpt=source.excerpt,
            )
        )
    return citations
