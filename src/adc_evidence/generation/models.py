from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CitationSource(BaseModel):
    citation_id: str
    chunk_id: str
    retrieval_document_id: str
    source_type: str
    title: str
    source_url: str
    excerpt: str


class CitationValidation(BaseModel):
    valid: bool
    cited_ids: list[str] = Field(default_factory=list)
    invalid_ids: list[str] = Field(default_factory=list)
    claim_count: int = 0
    cited_claim_count: int = 0
    coverage: float = 0.0


class GeneratorResponse(BaseModel):
    text: str
    backend: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    response_id: str | None = None


class AnswerResult(BaseModel):
    question: str
    status: Literal["answered", "refused", "error"]
    answer: str
    refusal_reason: str | None = None
    generator_backend: str
    model: str
    retrieval_mode: str
    retrieved_source_count: int = 0
    citations: list[CitationSource] = Field(default_factory=list)
    validation: CitationValidation | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    response_id: str | None = None
    latency_ms: int = 0
