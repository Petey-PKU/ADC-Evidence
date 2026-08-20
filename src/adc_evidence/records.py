from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source: str
    source_record_id: str
    retrieved_at: str
    source_url: str
    raw_path: str
    sha256: str
    dataset_version: str | None = None


class DocumentRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    document_id: str
    source: str
    source_record_id: str
    title: str
    abstract: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publication_date: str | None = None
    doi: str | None = None
    source_url: str
    raw_path: str
    checksum: str


class TrialRecord(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    nct_id: str
    brief_title: str
    official_title: str | None = None
    overall_status: str | None = None
    phases: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    sponsor: str | None = None
    enrollment: int | None = None
    start_date: str | None = None
    completion_date: str | None = None
    last_update_date: str | None = None
    primary_outcomes: list[str] = Field(default_factory=list)
    source_url: str
    raw_path: str
    checksum: str


class EntityLink(BaseModel):
    entity_type: str
    entity_id: str
    source_record_type: str
    source_record_id: str
    matched_alias: str
    match_method: str = "normalized_alias"


class EvidenceRecord(BaseModel):
    evidence_id: str
    subject_type: str
    subject_id: str
    source: str
    source_record_id: str
    predicate: str
    value: str
    evidence_text: str
    source_url: str
    confidence: float = Field(ge=0, le=1)
    review_status: str = "needs_review"
    extractor: str = "rule_v1"


class ADCdbRecord(BaseModel):
    adcdb_id: str
    adc_name: str
    brand_name: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    organization: str | None = None
    drug_status: str | None = None
    dar: float | None = None
    antibody_name: str | None = None
    antigen_name: str | None = None
    payload_name: str | None = None
    linker_name: str | None = None
    representative_indication: str | None = None
    detail_url: str
    raw_path: str
    checksum: str
    raw_fields: dict[str, Any] = Field(default_factory=dict)

