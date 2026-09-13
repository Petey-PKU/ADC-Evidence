from __future__ import annotations

import json
import hashlib
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Iterable

from adc_evidence.database import connect, create_database
from adc_evidence.evidence_policy import load_evidence_policy
from adc_evidence.facts import source_snapshot_rows
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


def recover_stale_ingestion_runs(
    database_path,
    *,
    now: str | None = None,
    stale_after_seconds: int = 3600,
) -> list[str]:
    """Close old interrupted runs so a process stop cannot leave ``running`` rows.

    A run is only recovered after the explicit age threshold.  This avoids
    changing a run owned by another live process while making interrupted
    command-line refreshes visible as terminal failures on the next start.
    """
    if stale_after_seconds < 0:
        raise ValueError("stale_after_seconds cannot be negative")
    now_value = datetime.now(timezone.utc) if now is None else datetime.fromisoformat(
        now.replace("Z", "+00:00")
    )
    if now_value.tzinfo is None:
        now_value = now_value.replace(tzinfo=timezone.utc)
    finished_at = now_value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    cutoff = now_value - timedelta(seconds=stale_after_seconds)
    create_database(database_path)
    recovered: list[str] = []
    with closing(connect(database_path)) as connection, connection:
        rows = connection.execute(
            "SELECT run_id, started_at FROM ingestion_runs WHERE status = 'running'"
        ).fetchall()
        for row in rows:
            try:
                started_at = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
            except ValueError:
                continue
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            if started_at > cutoff:
                continue
            run_id = str(row[0])
            error_text = "Run was interrupted or abandoned before completion; recovered on next start."
            summary = {
                "run_id": run_id,
                "finished_at": finished_at,
                "status": "failed",
                "errors": [error_text],
                "recovered_stale_run": True,
            }
            connection.execute(
                """
                UPDATE ingestion_runs
                SET finished_at = ?, status = 'failed', summary_json = ?, error_text = ?
                WHERE run_id = ? AND status = 'running'
                """,
                (finished_at, json.dumps(summary, ensure_ascii=False), error_text, run_id),
            )
            source_rows = connection.execute(
                "SELECT source, details_json FROM ingestion_source_runs "
                "WHERE run_id = ? AND status = 'running'",
                (run_id,),
            ).fetchall()
            for source_row in source_rows:
                try:
                    details = json.loads(str(source_row[1] or "{}"))
                except (TypeError, ValueError, json.JSONDecodeError):
                    details = {}
                if not isinstance(details, dict):
                    details = {}
                details["recovered_stale_run"] = True
                connection.execute(
                    """
                    UPDATE ingestion_source_runs
                    SET finished_at = ?, status = 'failed', error_text = ?, details_json = ?
                    WHERE run_id = ? AND source = ? AND status = 'running'
                    """,
                    (finished_at, error_text, json.dumps(details, ensure_ascii=False), run_id, source_row[0]),
                )
            recovered.append(run_id)
    return recovered


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


def start_source_run(
    database_path,
    run_id: str,
    source: str,
    started_at: str,
) -> None:
    """Start one independently observable source collection."""
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO ingestion_source_runs (
                run_id, source, started_at, status, details_json
            ) VALUES (?, ?, ?, 'running', '{}')
            ON CONFLICT(run_id, source) DO UPDATE SET
                started_at = excluded.started_at,
                finished_at = NULL,
                status = 'running',
                attempts = 0,
                expected_count = NULL,
                collected_count = 0,
                is_complete = 0,
                error_text = NULL,
                details_json = '{}'
            """,
            (run_id, source, started_at),
        )
        connection.execute(
            "DELETE FROM source_run_records WHERE run_id = ? AND source = ?",
            (run_id, source),
        )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _insert_source_event(
    connection,
    *,
    event_type: str,
    subject_type: str,
    subject_id: str,
    source: str,
    source_record_id: str | None,
    detected_at: str,
    old_value: object,
    new_value: object,
    details: dict[str, object],
) -> int:
    policy = load_evidence_policy().change_types[event_type]
    old_json = _canonical_json(old_value)
    new_json = _canonical_json(new_value)
    details_json = _canonical_json(details)
    digest = hashlib.sha256(
        "\x1f".join(
            (
                event_type,
                subject_type,
                subject_id,
                source,
                source_record_id or "",
                detected_at,
                old_json,
                new_json,
                details_json,
            )
        ).encode("utf-8")
    ).hexdigest()
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO change_events (
            event_id, event_type, severity, subject_type, subject_id,
            predicate, old_value_json, new_value_json, detected_at,
            source, source_record_id, snapshot_id, review_required,
            review_status, details_json, content_hash
        ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            f"chg_{digest[:32]}",
            event_type,
            policy.severity,
            subject_type,
            subject_id,
            old_json,
            new_json,
            detected_at,
            source,
            source_record_id,
            int(policy.review_required),
            "needs_review",
            details_json,
            digest,
        ),
    )
    return int(cursor.rowcount > 0)


def finish_source_run(
    database_path,
    run_id: str,
    source: str,
    finished_at: str,
    *,
    status: str,
    attempts: int,
    expected_count: int | None,
    record_ids: Iterable[str] = (),
    is_complete: bool,
    error_text: str | None = None,
    details: dict[str, object] | None = None,
) -> dict[str, object]:
    """Finish a source run and detect missing records only from complete snapshots."""
    record_ids = sorted(set(record_ids))
    details = details or {}
    missing_ids: list[str] = []
    event_count = 0
    with closing(connect(database_path)) as connection, connection:
        previous_run = connection.execute(
            """
            SELECT run_id
            FROM ingestion_source_runs
            WHERE source = ? AND run_id <> ?
              AND status = 'complete' AND is_complete = 1
            ORDER BY finished_at DESC, run_id DESC
            LIMIT 1
            """,
            (source, run_id),
        ).fetchone()
        previous_ids: set[str] = set()
        if previous_run is not None:
            previous_ids = {
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT source_record_id
                    FROM source_run_records
                    WHERE run_id = ? AND source = ?
                    """,
                    (str(previous_run[0]), source),
                ).fetchall()
            }

        connection.execute(
            """
            UPDATE ingestion_source_runs
            SET finished_at = ?, status = ?, attempts = ?,
                expected_count = ?, collected_count = ?, is_complete = ?,
                error_text = ?, details_json = ?
            WHERE run_id = ? AND source = ?
            """,
            (
                finished_at,
                status,
                attempts,
                expected_count,
                len(record_ids),
                int(is_complete),
                error_text,
                _canonical_json(details),
                run_id,
                source,
            ),
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO source_run_records (
                run_id, source, source_record_id, snapshot_id
            ) VALUES (?, ?, ?, NULL)
            """,
            [(run_id, source, record_id) for record_id in record_ids],
        )

        if status == "complete" and is_complete and previous_run is not None:
            missing_ids = sorted(previous_ids - set(record_ids))
            for record_id in missing_ids:
                event_count += _insert_source_event(
                    connection,
                    event_type="source.record_missing",
                    subject_type="source_record",
                    subject_id=f"{source}:{record_id}",
                    source=source,
                    source_record_id=record_id,
                    detected_at=finished_at,
                    old_value={"present": True},
                    new_value={"present": False},
                    details={
                        "run_id": run_id,
                        "previous_run_id": str(previous_run[0]),
                    },
                )
        elif status in {"partial", "failed"}:
            event_count += _insert_source_event(
                connection,
                event_type="source.collection_failed",
                subject_type="source",
                subject_id=source,
                source=source,
                source_record_id=None,
                detected_at=finished_at,
                old_value={},
                new_value={"status": status},
                details={"run_id": run_id, "error": error_text or ""},
            )
    return {
        "source": source,
        "status": status,
        "is_complete": is_complete,
        "collected_count": len(record_ids),
        "expected_count": expected_count,
        "missing_record_ids": missing_ids,
        "change_event_count": event_count,
    }


def source_run_statuses(database_path, run_id: str) -> list[dict[str, object]]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT run_id, source, started_at, finished_at, status, attempts,
                   expected_count, collected_count, is_complete, error_text,
                   details_json
            FROM ingestion_source_runs
            WHERE run_id = ?
            ORDER BY source
            """,
            (run_id,),
        ).fetchall()
    return [
        {
            **dict(row),
            "is_complete": bool(row["is_complete"]),
            "details": json.loads(row["details_json"]),
        }
        for row in rows
    ]


def upsert_source_records(
    database_path,
    records: Iterable[SourceRecord],
    *,
    ingestion_run_id: str | None = None,
    parser_version: str = "unspecified",
) -> int:
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
        connection.executemany(
            """
            INSERT OR IGNORE INTO source_snapshots (
                snapshot_id, source, source_record_id, fetched_at,
                source_updated_at, source_url, raw_path, content_hash,
                dataset_version, ingestion_run_id, parser_version
            ) VALUES (
                :snapshot_id, :source, :source_record_id, :fetched_at,
                :source_updated_at, :source_url, :raw_path, :content_hash,
                :dataset_version, :ingestion_run_id, :parser_version
            )
            """,
            source_snapshot_rows(
                records,
                ingestion_run_id=ingestion_run_id,
                parser_version=parser_version,
            ),
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
            "source_snapshot_count": "SELECT COUNT(*) FROM source_snapshots",
            "entity_link_count": "SELECT COUNT(*) FROM entity_links",
            "evidence_count": "SELECT COUNT(*) FROM evidence",
            "current_fact_count": (
                "SELECT COUNT(*) FROM facts "
                "WHERE valid_to IS NULL AND status = 'current'"
            ),
            "conflicted_fact_count": (
                "SELECT COUNT(*) FROM facts "
                "WHERE valid_to IS NULL AND status = 'conflicted'"
            ),
            "change_event_count": "SELECT COUNT(*) FROM change_events",
            "source_run_count": "SELECT COUNT(*) FROM ingestion_source_runs",
            "complete_source_run_count": (
                "SELECT COUNT(*) FROM ingestion_source_runs WHERE status = 'complete'"
            ),
            "failed_source_run_count": (
                "SELECT COUNT(*) FROM ingestion_source_runs "
                "WHERE status IN ('partial', 'failed')"
            ),
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
        metrics["source_run_status_counts"] = {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT status, COUNT(*) FROM ingestion_source_runs "
                "GROUP BY status ORDER BY status"
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
