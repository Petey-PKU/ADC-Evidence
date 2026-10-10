from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

from adc_evidence.ingestion.http import fetch_bytes, sha256_bytes, utc_now, write_snapshot
from adc_evidence.records import SourceRecord, TrialRecord


API_BASE = "https://clinicaltrials.gov/api/v2"


def build_trial_query(adc_names: list[str]) -> str:
    return " OR ".join(f'"{name}"' for name in adc_names)


def parse_trials_page(
    payload: dict[str, object],
    *,
    raw_path: str,
    checksum: str,
) -> list[TrialRecord]:
    records: list[TrialRecord] = []
    for study in payload.get("studies", []):
        protocol = study.get("protocolSection", {})
        identification = protocol.get("identificationModule", {})
        status = protocol.get("statusModule", {})
        design = protocol.get("designModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        interventions_module = protocol.get("armsInterventionsModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        outcomes_module = protocol.get("outcomesModule", {})

        nct_id = identification.get("nctId")
        brief_title = identification.get("briefTitle")
        if not nct_id or not brief_title:
            continue

        interventions: list[str] = []
        for intervention in interventions_module.get("interventions", []):
            name = intervention.get("name")
            if name:
                interventions.append(str(name))
            interventions.extend(str(item) for item in intervention.get("otherNames", []))

        primary_outcomes = [
            str(outcome.get("measure"))
            for outcome in outcomes_module.get("primaryOutcomes", [])
            if outcome.get("measure")
        ]

        enrollment_info = design.get("enrollmentInfo") or {}
        lead_sponsor = sponsor_module.get("leadSponsor") or {}
        records.append(
            TrialRecord(
                nct_id=str(nct_id),
                brief_title=str(brief_title),
                official_title=identification.get("officialTitle"),
                overall_status=status.get("overallStatus"),
                phases=[str(item) for item in design.get("phases", [])],
                conditions=[str(item) for item in conditions_module.get("conditions", [])],
                interventions=sorted(set(interventions)),
                sponsor=lead_sponsor.get("name"),
                enrollment=enrollment_info.get("count"),
                start_date=(status.get("startDateStruct") or {}).get("date"),
                completion_date=(status.get("completionDateStruct") or {}).get("date"),
                last_update_date=(status.get("lastUpdatePostDateStruct") or {}).get("date"),
                primary_outcomes=primary_outcomes,
                source_url=f"https://clinicaltrials.gov/study/{nct_id}",
                raw_path=raw_path,
                checksum=checksum,
            )
        )
    return records


def collect_clinical_trials(
    adc_names: list[str],
    raw_directory: Path,
    *,
    page_size: int = 100,
    max_pages: int = 5,
) -> tuple[
    list[TrialRecord],
    list[SourceRecord],
    str | None,
    dict[str, int | bool | None],
]:
    # Large ClinicalTrials.gov pages can exceed proxy/read-buffer limits.  A
    # bounded page also keeps each immutable source snapshot manageable while
    # max_pages controls the explicit coverage window.
    requested_page_size = page_size
    effective_page_size = min(max(1, page_size), 100)
    source_records: list[SourceRecord] = []
    trial_records: list[TrialRecord] = []
    retrieved_at = utc_now()

    version_url = f"{API_BASE}/version"
    version_content = fetch_bytes(version_url)
    version_payload = json.loads(version_content)
    version_path, version_checksum = write_snapshot(
        raw_directory / "version.json", version_content
    )
    dataset_version = version_payload.get("dataTimestamp")
    source_records.append(
        SourceRecord(
            source="clinicaltrials",
            source_record_id="dataset_version",
            retrieved_at=retrieved_at,
            source_url=version_url,
            raw_path=version_path,
            sha256=version_checksum,
            dataset_version=dataset_version,
        )
    )

    next_page_token: str | None = None
    total_count: int | None = None
    query = build_trial_query(adc_names)
    for page_number in range(1, max_pages + 1):
        parameters = {
            "format": "json",
            "pageSize": str(effective_page_size),
            "countTotal": "true",
            "query.term": query,
        }
        if next_page_token:
            parameters["pageToken"] = next_page_token
        url = f"{API_BASE}/studies?{urlencode(parameters)}"
        content = fetch_bytes(url, timeout=45)
        checksum = sha256_bytes(content)
        path, _ = write_snapshot(raw_directory / f"page_{page_number:03d}.json", content)
        payload = json.loads(content)
        if total_count is None:
            total_count = payload.get("totalCount")
        records = parse_trials_page(payload, raw_path=path, checksum=checksum)
        trial_records.extend(records)
        for record in records:
            source_records.append(
                SourceRecord(
                    source="clinicaltrials",
                    source_record_id=record.nct_id,
                    retrieved_at=retrieved_at,
                    source_url=record.source_url,
                    raw_path=path,
                    sha256=checksum,
                    dataset_version=dataset_version,
                    source_updated_at=record.last_update_date,
                )
            )
        next_page_token = payload.get("nextPageToken")
        if not next_page_token:
            break

    unique_trials = {record.nct_id: record for record in trial_records}
    unique_sources = {
        (record.source, record.source_record_id): record for record in source_records
    }
    collection_info = {
        "total_count": total_count,
        "collected_count": len(unique_trials),
        "truncated": bool(next_page_token),
        "requested_page_size": requested_page_size,
        "page_size": effective_page_size,
    }
    return (
        list(unique_trials.values()),
        list(unique_sources.values()),
        dataset_version,
        collection_info,
    )
