from __future__ import annotations

import re
from dataclasses import dataclass

from adc_evidence.generation.models import CitationSource, CitationValidation
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


def _claim_lines(answer: str) -> list[str]:
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
    claims = _claim_lines(answer)
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
