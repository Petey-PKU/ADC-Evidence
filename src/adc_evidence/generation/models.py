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


AnswerRoute = Literal[
    "structured_fact",
    "comparison",
    "change_query",
    "trial_lookup",
    "literature_evidence",
    "refusal",
]


class QuestionPlan(BaseModel):
    route: AnswerRoute
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    adc_ids: list[str] = Field(default_factory=list)
    adc_names: list[str] = Field(default_factory=list)
    predicates: list[str] = Field(default_factory=list)
    nct_ids: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    days: int | None = None


class AnswerGap(BaseModel):
    item: str
    reason: Literal[
        "missing_direct_evidence",
        "conflicted",
        "unknown_entity",
        "no_matching_record",
        "validation_failed",
        "unsupported_route",
    ]
    detail: str


class AtomicClaim(BaseModel):
    claim_id: str
    text: str
    subject_type: str
    subject_id: str
    predicate: str
    value: object
    citation_ids: list[str] = Field(default_factory=list)
    support_kind: Literal["structured", "text"]
    validation_status: Literal["supported", "unsupported"]


class ClaimSupport(BaseModel):
    claim_id: str
    supported: bool
    citation_ids: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    missing_terms: list[str] = Field(default_factory=list)
    reason: str | None = None


class ClaimValidationSummary(BaseModel):
    valid: bool
    support_kind: Literal["structured", "text"]
    claim_count: int = 0
    supported_claim_count: int = 0
    unsupported_claim_count: int = 0
    claims: list[ClaimSupport] = Field(default_factory=list)


class GeneratorResponse(BaseModel):
    text: str
    backend: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    response_id: str | None = None


class AnswerResult(BaseModel):
    question: str
    status: Literal["answered", "partial", "refused", "error"]
    answer: str
    refusal_reason: str | None = None
    generator_backend: str
    model: str
    retrieval_mode: str
    route: AnswerRoute = "literature_evidence"
    route_reason: str | None = None
    retrieved_source_count: int = 0
    citations: list[CitationSource] = Field(default_factory=list)
    validation: CitationValidation | None = None
    claim_validation: ClaimValidationSummary | None = None
    claims: list[AtomicClaim] = Field(default_factory=list)
    unanswered: list[AnswerGap] = Field(default_factory=list)
    data_version: dict[str, object] | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    response_id: str | None = None
    latency_ms: int = 0
