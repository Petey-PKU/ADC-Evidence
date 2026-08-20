from __future__ import annotations

import json
from contextlib import closing
from typing import Iterable

from adc_evidence.database import connect, create_database
from adc_evidence.records import (
    DocumentRecord,
    EntityLink,
    EvidenceRecord,
    SourceRecord,
    TrialRecord,
)


def start_ingestion_run(
    database_path,
    run_id: str,
    started_at: str,
    parameters: dict[str, object],
) -> None:
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO ingestion_runs (
                run_id, started_at, status, parameters_json
            ) VALUES (?, ?, 'running', ?)
            """,
            (run_id, started_at, json.dumps(parameters, ensure_ascii=False)),
        )


def finish_ingestion_run(
    database_path,
    run_id: str,
    finished_at: str,
    status: str,
    summary: dict[str, object],
    error_text: str | None = None,
) -> None:
    with closing(connect(database_path)) as connection, connection:
        connection.execute(
            """
            UPDATE ingestion_runs
            SET finished_at = ?, status = ?, summary_json = ?, error_text = ?
            WHERE run_id = ?
            """,
            (
                finished_at,
                status,
                json.dumps(summary, ensure_ascii=False),
                error_text,
                run_id,
            ),
        )


def upsert_source_records(database_path, records: Iterable[SourceRecord]) -> int:
    records = list(records)
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.executemany(
            """
            INSERT INTO source_records (
                source, source_record_id, retrieved_at, source_url,
                raw_path, sha256, dataset_version
            ) VALUES (
                :source, :source_record_id, :retrieved_at, :source_url,
                :raw_path, :sha256, :dataset_version
            )
            ON CONFLICT(source, source_record_id) DO UPDATE SET
                retrieved_at = excluded.retrieved_at,
                source_url = excluded.source_url,
                raw_path = excluded.raw_path,
                sha256 = excluded.sha256,
                dataset_version = excluded.dataset_version
            """,
            [record.model_dump() for record in records],
        )
    return len(records)


def upsert_documents(database_path, records: Iterable[DocumentRecord]) -> int:
    records = list(records)
    create_database(database_path)
    values = []
    for record in records:
        item = record.model_dump()
        item["authors_json"] = json.dumps(item.pop("authors"), ensure_ascii=False)
        values.append(item)
    with closing(connect(database_path)) as connection, connection:
        connection.executemany(
            """
            INSERT INTO documents (
                document_id, source, source_record_id, title, abstract,
                authors_json, journal, publication_date, doi, source_url,
                raw_path, checksum
            ) VALUES (
                :document_id, :source, :source_record_id, :title, :abstract,
                :authors_json, :journal, :publication_date, :doi, :source_url,
                :raw_path, :checksum
            )
            ON CONFLICT(document_id) DO UPDATE SET
                title = excluded.title,
                abstract = excluded.abstract,
                authors_json = excluded.authors_json,
                journal = excluded.journal,
                publication_date = excluded.publication_date,
                doi = excluded.doi,
                source_url = excluded.source_url,
                raw_path = excluded.raw_path,
                checksum = excluded.checksum
            """,
            values,
        )
    return len(records)


def upsert_trials(database_path, records: Iterable[TrialRecord]) -> int:
    records = list(records)
    values = []
    for record in records:
        item = record.model_dump()
        for field in ("phases", "conditions", "interventions", "primary_outcomes"):
            item[f"{field}_json"] = json.dumps(item.pop(field), ensure_ascii=False)
        values.append(item)
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.executemany(
            """
            INSERT INTO trials (
                nct_id, brief_title, official_title, overall_status,
                phases_json, conditions_json, interventions_json, sponsor,
                enrollment, start_date, completion_date, last_update_date,
                primary_outcomes_json, source_url, raw_path, checksum
            ) VALUES (
                :nct_id, :brief_title, :official_title, :overall_status,
                :phases_json, :conditions_json, :interventions_json, :sponsor,
                :enrollment, :start_date, :completion_date, :last_update_date,
                :primary_outcomes_json, :source_url, :raw_path, :checksum
            )
            ON CONFLICT(nct_id) DO UPDATE SET
                brief_title = excluded.brief_title,
                official_title = excluded.official_title,
                overall_status = excluded.overall_status,
                phases_json = excluded.phases_json,
                conditions_json = excluded.conditions_json,
                interventions_json = excluded.interventions_json,
                sponsor = excluded.sponsor,
                enrollment = excluded.enrollment,
                start_date = excluded.start_date,
                completion_date = excluded.completion_date,
                last_update_date = excluded.last_update_date,
                primary_outcomes_json = excluded.primary_outcomes_json,
                source_url = excluded.source_url,
                raw_path = excluded.raw_path,
                checksum = excluded.checksum
            """,
            values,
        )
    return len(records)


def upsert_entity_links(database_path, records: Iterable[EntityLink]) -> int:
    records = list(records)
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.executemany(
            """
            INSERT OR REPLACE INTO entity_links (
                entity_type, entity_id, source_record_type, source_record_id,
                matched_alias, match_method
            ) VALUES (
                :entity_type, :entity_id, :source_record_type, :source_record_id,
                :matched_alias, :match_method
            )
            """,
            [record.model_dump() for record in records],
        )
    return len(records)


def upsert_evidence(database_path, records: Iterable[EvidenceRecord]) -> int:
    records = list(records)
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.executemany(
            """
            INSERT INTO evidence (
                evidence_id, subject_type, subject_id, source,
                source_record_id, predicate, value, evidence_text,
                source_url, confidence, review_status, extractor
            ) VALUES (
                :evidence_id, :subject_type, :subject_id, :source,
                :source_record_id, :predicate, :value, :evidence_text,
                :source_url, :confidence, :review_status, :extractor
            )
            ON CONFLICT(evidence_id) DO UPDATE SET
                value = excluded.value,
                evidence_text = excluded.evidence_text,
                source_url = excluded.source_url,
                confidence = excluded.confidence,
                review_status = excluded.review_status,
                extractor = excluded.extractor
            """,
            [record.model_dump() for record in records],
        )
    return len(records)


def upsert_external_identifier(
    database_path,
    *,
    entity_type: str,
    entity_id: str,
    source: str,
    external_id: str,
    source_url: str,
) -> None:
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO external_identifiers (
                entity_type, entity_id, source, external_id, source_url
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (entity_type, entity_id, source, external_id, source_url),
        )


def upsert_entity_aliases(
    database_path,
    records: Iterable[dict[str, str]],
) -> int:
    records = list(records)
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO entity_aliases (
                entity_type, entity_id, canonical_name, alias,
                normalized_alias, source
            ) VALUES (
                :entity_type, :entity_id, :canonical_name, :alias,
                :normalized_alias, :source
            )
            """,
            records,
        )
    return len(records)


def data_quality_metrics(database_path) -> dict[str, object]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        scalar_queries = {
            "adc_count": "SELECT COUNT(*) FROM adcs",
            "document_count": "SELECT COUNT(*) FROM documents",
            "document_with_abstract_count": (
                "SELECT COUNT(*) FROM documents WHERE abstract IS NOT NULL AND abstract <> ''"
            ),
            "trial_count": "SELECT COUNT(*) FROM trials",
            "source_record_count": "SELECT COUNT(*) FROM source_records",
            "entity_link_count": "SELECT COUNT(*) FROM entity_links",
            "evidence_count": "SELECT COUNT(*) FROM evidence",
            "adcdb_linked_adc_count": (
                "SELECT COUNT(DISTINCT entity_id) FROM external_identifiers "
                "WHERE entity_type = 'adc' AND source = 'adcdb'"
            ),
            "adcdb_unlinked_source_count": (
                "SELECT COUNT(*) FROM source_records AS source_record "
                "WHERE source_record.source = 'adcdb' AND NOT EXISTS ("
                "SELECT 1 FROM external_identifiers AS external_id "
                "WHERE external_id.source = 'adcdb' "
                "AND external_id.external_id = source_record.source_record_id)"
            ),
            "trial_linked_adc_count": (
                "SELECT COUNT(DISTINCT entity_id) FROM entity_links "
                "WHERE entity_type = 'adc' AND source_record_type = 'trial'"
            ),
            "document_linked_adc_count": (
                "SELECT COUNT(DISTINCT entity_id) FROM entity_links "
                "WHERE entity_type = 'adc' AND source_record_type = 'document'"
            ),
        }
        metrics = {
            name: connection.execute(query).fetchone()[0]
            for name, query in scalar_queries.items()
        }
        metrics["source_counts"] = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT source, COUNT(*) FROM source_records GROUP BY source ORDER BY source"
            ).fetchall()
        }
        metrics["trial_status_counts"] = {
            (row[0] or "UNKNOWN"): row[1]
            for row in connection.execute(
                "SELECT overall_status, COUNT(*) FROM trials GROUP BY overall_status "
                "ORDER BY COUNT(*) DESC"
            ).fetchall()
        }
        metrics["adcdb_unlinked_adc_names"] = [
            row[0]
            for row in connection.execute(
                "SELECT adc.adc_name FROM adcs AS adc WHERE NOT EXISTS ("
                "SELECT 1 FROM external_identifiers AS external_id "
                "WHERE external_id.entity_type = 'adc' "
                "AND external_id.entity_id = adc.adc_id "
                "AND external_id.source = 'adcdb') ORDER BY adc.adc_name"
            ).fetchall()
        ]
        metrics["adc_missing_dar_names"] = [
            row[0]
            for row in connection.execute(
                "SELECT adc_name FROM adcs WHERE dar IS NULL ORDER BY adc_name"
            ).fetchall()
        ]
    document_count = int(metrics["document_count"])
    metrics["abstract_coverage"] = (
        round(int(metrics["document_with_abstract_count"]) / document_count, 4)
        if document_count
        else 0.0
    )
    return metrics
