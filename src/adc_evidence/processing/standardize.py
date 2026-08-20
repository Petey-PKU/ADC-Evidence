from __future__ import annotations

import hashlib
import re

from adc_evidence.models import ADCRecord, DevelopmentStatus, LinkerType, ReviewStatus
from adc_evidence.processing.normalize import AliasMatch, EntityNormalizer, normalize_text
from adc_evidence.records import ADCdbRecord, DocumentRecord, EntityLink, EvidenceRecord, TrialRecord


def stable_evidence_id(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return "ev_" + hashlib.sha256(payload).hexdigest()[:24]


def evidence_excerpt(text: str, match: AliasMatch, max_length: int = 600) -> str:
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    for sentence in sentences:
        if f" {match.matched_alias} " in f" {normalize_text(sentence)} ":
            return sentence[:max_length]
    return text[:max_length]


def document_links_and_evidence(
    documents: list[DocumentRecord],
    normalizer: EntityNormalizer,
) -> tuple[list[EntityLink], list[EvidenceRecord]]:
    links: list[EntityLink] = []
    evidence: list[EvidenceRecord] = []
    for document in documents:
        full_text = "\n".join(
            item for item in (document.title, document.abstract or "") if item
        )
        for match in normalizer.find_matches(full_text):
            links.append(
                EntityLink(
                    entity_type=match.entity_type,
                    entity_id=match.entity_id,
                    source_record_type="document",
                    source_record_id=document.document_id,
                    matched_alias=match.matched_alias,
                )
            )
            evidence.append(
                EvidenceRecord(
                    evidence_id=stable_evidence_id(
                        "pubmed",
                        document.source_record_id,
                        match.entity_type,
                        match.entity_id,
                        "mentions",
                    ),
                    subject_type=match.entity_type,
                    subject_id=match.entity_id,
                    source="pubmed",
                    source_record_id=document.source_record_id,
                    predicate="mentions",
                    value=match.canonical_name,
                    evidence_text=evidence_excerpt(full_text, match),
                    source_url=document.source_url,
                    confidence=0.9,
                )
            )
    return links, evidence


def trial_links_and_evidence(
    trials: list[TrialRecord],
    normalizer: EntityNormalizer,
) -> tuple[list[EntityLink], list[EvidenceRecord]]:
    links: list[EntityLink] = []
    evidence: list[EvidenceRecord] = []
    for trial in trials:
        full_text = "\n".join(
            [
                trial.brief_title,
                trial.official_title or "",
                *trial.interventions,
            ]
        )
        for match in normalizer.find_matches(full_text, entity_types=("adc", "target")):
            links.append(
                EntityLink(
                    entity_type=match.entity_type,
                    entity_id=match.entity_id,
                    source_record_type="trial",
                    source_record_id=trial.nct_id,
                    matched_alias=match.matched_alias,
                )
            )
            evidence.append(
                EvidenceRecord(
                    evidence_id=stable_evidence_id(
                        "clinicaltrials",
                        trial.nct_id,
                        match.entity_type,
                        match.entity_id,
                        "trial_status",
                    ),
                    subject_type=match.entity_type,
                    subject_id=match.entity_id,
                    source="clinicaltrials",
                    source_record_id=trial.nct_id,
                    predicate="trial_status",
                    value=trial.overall_status or "UNKNOWN",
                    evidence_text=(
                        f"{trial.brief_title}; interventions: "
                        f"{', '.join(trial.interventions)}; status: "
                        f"{trial.overall_status or 'UNKNOWN'}"
                    )[:600],
                    source_url=trial.source_url,
                    confidence=0.98,
                )
            )
    return links, evidence


def _development_status(value: str | None) -> DevelopmentStatus:
    normalized = normalize_text(value or "")
    if "approved" in normalized:
        return DevelopmentStatus.APPROVED
    if any(term in normalized for term in ("discontinued", "withdrawn", "terminated")):
        return DevelopmentStatus.DISCONTINUED
    if normalized:
        return DevelopmentStatus.INVESTIGATIONAL
    return DevelopmentStatus.UNKNOWN


def adcdb_to_adc_record(
    record: ADCdbRecord,
    normalizer: EntityNormalizer,
    fallback: ADCRecord,
) -> ADCRecord:
    target = normalizer.canonical_target(record.antigen_name or "") or fallback.target
    aliases = sorted(
        {
            *fallback.aliases,
            *record.synonyms,
            *([record.brand_name] if record.brand_name else []),
        }
    )
    return ADCRecord(
        adc_id=fallback.adc_id,
        adc_name=fallback.adc_name,
        aliases=aliases,
        target=target,
        antibody=record.antibody_name or fallback.antibody,
        linker_name=record.linker_name or fallback.linker_name,
        linker_type=fallback.linker_type or LinkerType.UNKNOWN,
        payload_name=record.payload_name or fallback.payload_name,
        payload_class=fallback.payload_class,
        dar=record.dar if record.dar is not None else fallback.dar,
        indication=record.representative_indication or fallback.indication,
        development_status=_development_status(record.drug_status),
        company=record.organization or fallback.company,
        source_url=record.detail_url,
        data_review_status=ReviewStatus.NEEDS_REVIEW,
    )


def adcdb_evidence(
    record: ADCdbRecord,
    adc_id: str,
) -> list[EvidenceRecord]:
    facts = {
        "adc_name": record.adc_name,
        "drug_status": record.drug_status,
        "dar": str(record.dar) if record.dar is not None else None,
        "antibody": record.antibody_name,
        "antigen": record.antigen_name,
        "payload": record.payload_name,
        "linker": record.linker_name,
        "organization": record.organization,
    }
    evidence: list[EvidenceRecord] = []
    for predicate, value in facts.items():
        if not value:
            continue
        evidence.append(
            EvidenceRecord(
                evidence_id=stable_evidence_id(
                    "adcdb", record.adcdb_id, adc_id, predicate
                ),
                subject_type="adc",
                subject_id=adc_id,
                source="adcdb",
                source_record_id=record.adcdb_id,
                predicate=predicate,
                value=value,
                evidence_text=f"{predicate}: {value}",
                source_url=record.detail_url,
                confidence=0.98,
            )
        )
    return evidence

