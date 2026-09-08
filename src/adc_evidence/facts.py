from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adc_evidence.database import connect, create_database
from adc_evidence.evidence_policy import EvidencePolicy, load_evidence_policy
from adc_evidence.models import ADCRecord
from adc_evidence.processing.normalize import EntityNormalizer, normalize_text
from adc_evidence.records import ADCdbRecord, DocumentRecord, SourceRecord, TrialRecord


class ObservedFactValue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: Any
    display_value: str | None = None
    source_locator: str = ""
    evidence_text: str | None = None

    @model_validator(mode="after")
    def value_must_be_present(self) -> "ObservedFactValue":
        if self.value is None:
            raise ValueError("observed fact values cannot be null")
        if isinstance(self.value, str) and not self.value.strip():
            raise ValueError("observed fact string values cannot be empty")
        return self


class FactObservationSet(BaseModel):
    """A complete source observation for one subject and predicate."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    values: list[ObservedFactValue]
    source: str = Field(min_length=1)
    source_record_id: str = Field(min_length=1)
    observed_at: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    snapshot_id: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    extractor: str = "structured_v1"
    review_status: str = "needs_review"


def _digest(*parts: str) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def stable_snapshot_id(
    source: str,
    source_record_id: str,
    content_hash: str,
) -> str:
    return "snap_" + _digest(source, source_record_id, content_hash)[:32]


def source_snapshot_rows(
    records: Iterable[SourceRecord],
    *,
    ingestion_run_id: str | None = None,
    parser_version: str = "unspecified",
) -> list[dict[str, object]]:
    return [
        {
            "snapshot_id": stable_snapshot_id(
                record.source,
                record.source_record_id,
                record.sha256,
            ),
            "source": record.source,
            "source_record_id": record.source_record_id,
            "fetched_at": record.retrieved_at,
            "source_updated_at": record.source_updated_at,
            "source_url": record.source_url,
            "raw_path": record.raw_path,
            "content_hash": record.sha256,
            "dataset_version": record.dataset_version,
            "ingestion_run_id": ingestion_run_id,
            "parser_version": parser_version,
        }
        for record in records
    ]


def verify_source_snapshots(
    database_path: Path,
    *,
    relative_root: Path | None = None,
) -> list[dict[str, object]]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT snapshot_id, source, source_record_id, raw_path, content_hash
            FROM source_snapshots
            ORDER BY source, source_record_id, fetched_at
            """
        ).fetchall()

    results: list[dict[str, object]] = []
    for row in rows:
        raw_path = Path(str(row["raw_path"]))
        if not raw_path.is_absolute() and relative_root is not None:
            raw_path = relative_root / raw_path
        if not raw_path.exists():
            status = "missing"
            actual_hash = None
        else:
            actual_hash = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            status = (
                "valid"
                if actual_hash == str(row["content_hash"])
                else "hash_mismatch"
            )
        results.append(
            {
                "snapshot_id": str(row["snapshot_id"]),
                "source": str(row["source"]),
                "source_record_id": str(row["source_record_id"]),
                "raw_path": str(raw_path),
                "expected_hash": str(row["content_hash"]),
                "actual_hash": actual_hash,
                "status": status,
            }
        )
    return results


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return {
            str(key): _normalize_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize_value(item) for item in value]
    return value


def _value_parts(
    observed: ObservedFactValue,
) -> tuple[str, str, str]:
    normalized = _normalize_value(observed.value)
    normalized_json = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    value_hash = hashlib.sha256(normalized_json.encode("utf-8")).hexdigest()
    display_value = observed.display_value
    if display_value is None:
        display_value = (
            normalized
            if isinstance(normalized, str)
            else json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        )
    return normalized_json, str(display_value), value_hash


def _current_rows(connection, observation: FactObservationSet):
    return connection.execute(
        """
        SELECT evidence.*, fact.value_hash, fact.normalized_value_json,
               fact.display_value
        FROM fact_evidence AS evidence
        JOIN facts AS fact ON fact.fact_id = evidence.fact_id
        WHERE fact.subject_type = ?
          AND fact.subject_id = ?
          AND fact.predicate = ?
          AND evidence.source = ?
          AND evidence.source_record_id = ?
          AND evidence.is_current = 1
        ORDER BY evidence.fact_evidence_id
        """,
        (
            observation.subject_type,
            observation.subject_id,
            observation.predicate,
            observation.source,
            observation.source_record_id,
        ),
    ).fetchall()


def _canonical_values(connection, observation: FactObservationSet) -> list[Any]:
    rows = connection.execute(
        """
        SELECT DISTINCT normalized_value_json
        FROM facts
        WHERE subject_type = ?
          AND subject_id = ?
          AND predicate = ?
          AND valid_to IS NULL
          AND status IN ('current', 'conflicted')
        ORDER BY normalized_value_json
        """,
        (
            observation.subject_type,
            observation.subject_id,
            observation.predicate,
        ),
    ).fetchall()
    return [json.loads(str(row["normalized_value_json"])) for row in rows]


def _has_conflict(connection, observation: FactObservationSet) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM facts
        WHERE subject_type = ?
          AND subject_id = ?
          AND predicate = ?
          AND valid_to IS NULL
          AND status = 'conflicted'
        LIMIT 1
        """,
        (
            observation.subject_type,
            observation.subject_id,
            observation.predicate,
        ),
    ).fetchone()
    return row is not None


def _find_supported_fact(
    connection,
    observation: FactObservationSet,
    value_hash: str,
):
    return connection.execute(
        """
        SELECT fact.*
        FROM facts AS fact
        WHERE fact.subject_type = ?
          AND fact.subject_id = ?
          AND fact.predicate = ?
          AND fact.value_hash = ?
          AND fact.valid_to IS NULL
          AND EXISTS (
              SELECT 1
              FROM fact_evidence AS evidence
              WHERE evidence.fact_id = fact.fact_id
                AND evidence.is_current = 1
          )
        ORDER BY fact.created_at DESC, fact.fact_id DESC
        LIMIT 1
        """,
        (
            observation.subject_type,
            observation.subject_id,
            observation.predicate,
            value_hash,
        ),
    ).fetchone()


def _reconcile_facts(
    connection,
    observation: FactObservationSet,
    policy: EvidencePolicy,
) -> None:
    field_policy = policy.fields[observation.predicate]
    rows = connection.execute(
        """
        SELECT fact.fact_id, fact.value_hash, evidence.source
        FROM facts AS fact
        LEFT JOIN fact_evidence AS evidence
          ON evidence.fact_id = fact.fact_id
         AND evidence.is_current = 1
        WHERE fact.subject_type = ?
          AND fact.subject_id = ?
          AND fact.predicate = ?
          AND fact.valid_to IS NULL
        ORDER BY fact.fact_id
        """,
        (
            observation.subject_type,
            observation.subject_id,
            observation.predicate,
        ),
    ).fetchall()

    sources_by_fact: dict[str, set[str]] = defaultdict(set)
    value_by_fact: dict[str, str] = {}
    for row in rows:
        fact_id = str(row["fact_id"])
        value_by_fact[fact_id] = str(row["value_hash"])
        if row["source"] is not None:
            sources_by_fact[fact_id].add(str(row["source"]))

    unsupported = set(value_by_fact) - set(sources_by_fact)
    if unsupported:
        placeholders = ",".join("?" for _ in unsupported)
        connection.execute(
            f"""
            UPDATE facts
            SET status = 'superseded', valid_to = ?, updated_at = ?
            WHERE fact_id IN ({placeholders})
            """,
            (
                observation.observed_at,
                observation.observed_at,
                *sorted(unsupported),
            ),
        )

    active_fact_ids = set(sources_by_fact)
    if not active_fact_ids:
        return

    statuses: dict[str, str]
    distinct_values = {value_by_fact[fact_id] for fact_id in active_fact_ids}
    if field_policy.conflict_resolution == "require_review":
        status = "conflicted" if len(distinct_values) > 1 else "current"
        statuses = {fact_id: status for fact_id in active_fact_ids}
    elif field_policy.conflict_resolution == "preserve_all":
        statuses = {fact_id: "current" for fact_id in active_fact_ids}
    else:
        source_rank = {
            source: rank
            for rank, source in enumerate(field_policy.preferred_sources)
        }
        unknown_rank = len(source_rank) + 1
        rank_by_fact = {
            fact_id: min(
                (source_rank.get(source, unknown_rank) for source in sources),
                default=unknown_rank,
            )
            for fact_id, sources in sources_by_fact.items()
        }
        best_rank = min(rank_by_fact.values())
        statuses = {
            fact_id: ("current" if rank == best_rank else "superseded")
            for fact_id, rank in rank_by_fact.items()
        }

    for fact_id, status in statuses.items():
        connection.execute(
            """
            UPDATE facts
            SET status = ?, valid_to = NULL, updated_at = ?
            WHERE fact_id = ?
            """,
            (status, observation.observed_at, fact_id),
        )


def _field_change_type(predicate: str, policy: EvidencePolicy) -> str:
    exact_name = f"{predicate}.changed"
    if exact_name in policy.change_types:
        return exact_name
    if predicate.startswith("adc.") and "adc.structure.changed" in policy.change_types:
        return "adc.structure.changed"
    return "fact.value_changed"


def _insert_change_event(
    connection,
    *,
    observation: FactObservationSet,
    policy: EvidencePolicy,
    event_type: str,
    old_values: list[Any],
    new_values: list[Any],
    details: dict[str, object],
) -> int:
    event_policy = policy.change_types[event_type]
    old_value_json = json.dumps(
        old_values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    new_value_json = json.dumps(
        new_values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    details_json = json.dumps(
        details,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = _digest(
        event_type,
        observation.subject_type,
        observation.subject_id,
        observation.predicate,
        observation.source,
        observation.source_record_id,
        observation.snapshot_id or "",
        observation.observed_at,
        old_value_json,
        new_value_json,
        details_json,
    )
    event_id = "chg_" + content_hash[:32]
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO change_events (
            event_id, event_type, severity, subject_type, subject_id,
            predicate, old_value_json, new_value_json, detected_at,
            source, source_record_id, snapshot_id, review_required,
            review_status, details_json, content_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event_type,
            event_policy.severity,
            observation.subject_type,
            observation.subject_id,
            observation.predicate,
            old_value_json,
            new_value_json,
            observation.observed_at,
            observation.source,
            observation.source_record_id,
            observation.snapshot_id,
            int(event_policy.review_required),
            "needs_review",
            details_json,
            content_hash,
        ),
    )
    return int(cursor.rowcount > 0)


def record_fact_sets(
    database_path: Path,
    observations: Iterable[FactObservationSet],
    *,
    policy: EvidencePolicy | None = None,
) -> dict[str, int]:
    """Persist complete field observations and reconcile canonical facts."""
    observation_list = [
        item
        if isinstance(item, FactObservationSet)
        else FactObservationSet.model_validate(item)
        for item in observations
    ]
    policy = policy or load_evidence_policy()
    group_keys = [
        (
            item.subject_type,
            item.subject_id,
            item.predicate,
            item.source,
            item.source_record_id,
        )
        for item in observation_list
    ]
    if len(group_keys) != len(set(group_keys)):
        raise ValueError("record_fact_sets received duplicate observation groups")

    summary = {
        "groups_processed": 0,
        "idempotent_groups": 0,
        "facts_created": 0,
        "evidence_created": 0,
        "changes_created": 0,
    }
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        for observation in observation_list:
            if observation.predicate not in policy.fields:
                raise ValueError(
                    f"Unknown evidence policy field: {observation.predicate}"
                )
            if observation.source not in policy.sources:
                raise ValueError(
                    f"Unknown evidence policy source: {observation.source}"
                )
            if observation.review_status not in policy.review_statuses:
                raise ValueError(
                    f"Unknown review status: {observation.review_status}"
                )
            if observation.snapshot_id is not None:
                snapshot = connection.execute(
                    """
                    SELECT source, source_record_id
                    FROM source_snapshots
                    WHERE snapshot_id = ?
                    """,
                    (observation.snapshot_id,),
                ).fetchone()
                if snapshot is None:
                    raise ValueError(
                        f"Unknown source snapshot: {observation.snapshot_id}"
                    )
                if (
                    str(snapshot["source"]) != observation.source
                    or str(snapshot["source_record_id"])
                    != observation.source_record_id
                ):
                    raise ValueError(
                        "Snapshot source identity does not match observation"
                    )

            field_policy = policy.fields[observation.predicate]
            incoming: dict[str, dict[str, object]] = {}
            for value in observation.values:
                normalized_json, display_value, value_hash = _value_parts(value)
                evidence_text = value.evidence_text or (
                    f"{observation.predicate}: {display_value}"
                )
                evidence_hash = _digest(
                    observation.subject_type,
                    observation.subject_id,
                    observation.predicate,
                    observation.source,
                    observation.source_record_id,
                    observation.snapshot_id or "",
                    value.source_locator,
                    value_hash,
                    evidence_text,
                )
                evidence_id = "fe_" + evidence_hash[:32]
                incoming[evidence_id] = {
                    "fact_evidence_id": evidence_id,
                    "normalized_value_json": normalized_json,
                    "display_value": display_value,
                    "value_hash": value_hash,
                    "source_locator": value.source_locator,
                    "evidence_text": evidence_text,
                    "content_hash": evidence_hash,
                }

            current_rows = _current_rows(connection, observation)
            current_ids = {
                str(row["fact_evidence_id"]) for row in current_rows
            }
            if current_ids == set(incoming):
                summary["idempotent_groups"] += 1
                continue

            summary["groups_processed"] += 1
            before_canonical = _canonical_values(connection, observation)
            before_conflict = _has_conflict(connection, observation)
            before_source_values = sorted(
                {
                    str(row["normalized_value_json"])
                    for row in current_rows
                }
            )
            old_fact_by_value = {
                str(row["value_hash"]): str(row["fact_id"])
                for row in current_rows
            }
            if current_rows:
                connection.execute(
                    """
                    UPDATE fact_evidence
                    SET is_current = 0, valid_to = ?
                    WHERE source = ?
                      AND source_record_id = ?
                      AND is_current = 1
                      AND fact_id IN (
                          SELECT fact_id
                          FROM facts
                          WHERE subject_type = ?
                            AND subject_id = ?
                            AND predicate = ?
                      )
                    """,
                    (
                        observation.observed_at,
                        observation.source,
                        observation.source_record_id,
                        observation.subject_type,
                        observation.subject_id,
                        observation.predicate,
                    ),
                )

            for item in incoming.values():
                value_hash = str(item["value_hash"])
                fact = _find_supported_fact(
                    connection,
                    observation,
                    value_hash,
                )
                fact_id = (
                    str(fact["fact_id"])
                    if fact is not None
                    else old_fact_by_value.get(value_hash)
                )
                if fact_id is None:
                    fact_hash = _digest(
                        observation.subject_type,
                        observation.subject_id,
                        observation.predicate,
                        value_hash,
                        observation.observed_at,
                        observation.snapshot_id or observation.source,
                    )
                    fact_id = "fact_" + fact_hash[:32]
                    fact_content_hash = _digest(
                        observation.subject_type,
                        observation.subject_id,
                        observation.predicate,
                        str(item["normalized_value_json"]),
                        field_policy.value_type,
                        policy.policy_version,
                    )
                    connection.execute(
                        """
                        INSERT INTO facts (
                            fact_id, subject_type, subject_id, predicate,
                            normalized_value_json, display_value, value_type,
                            value_hash, status, valid_from, valid_to,
                            review_status, policy_version, content_hash,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'current', ?, NULL,
                                  ?, ?, ?, ?, ?)
                        """,
                        (
                            fact_id,
                            observation.subject_type,
                            observation.subject_id,
                            observation.predicate,
                            item["normalized_value_json"],
                            item["display_value"],
                            field_policy.value_type,
                            value_hash,
                            observation.observed_at,
                            observation.review_status,
                            policy.policy_version,
                            fact_content_hash,
                            observation.observed_at,
                            observation.observed_at,
                        ),
                    )
                    summary["facts_created"] += 1

                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO fact_evidence (
                        fact_evidence_id, fact_id, snapshot_id, source,
                        source_record_id, source_locator, evidence_text,
                        source_url, confidence, extractor, observed_at,
                        valid_to, is_current, review_status, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 1, ?, ?)
                    """,
                    (
                        item["fact_evidence_id"],
                        fact_id,
                        observation.snapshot_id,
                        observation.source,
                        observation.source_record_id,
                        item["source_locator"],
                        item["evidence_text"],
                        observation.source_url,
                        observation.confidence,
                        observation.extractor,
                        observation.observed_at,
                        observation.review_status,
                        item["content_hash"],
                    ),
                )
                summary["evidence_created"] += int(cursor.rowcount > 0)

            _reconcile_facts(connection, observation, policy)
            after_canonical = _canonical_values(connection, observation)
            after_conflict = _has_conflict(connection, observation)
            after_source_values = sorted(
                {
                    str(item["normalized_value_json"])
                    for item in incoming.values()
                }
            )

            if current_rows and before_source_values != after_source_values:
                summary["changes_created"] += _insert_change_event(
                    connection,
                    observation=observation,
                    policy=policy,
                    event_type=_field_change_type(
                        observation.predicate,
                        policy,
                    ),
                    old_values=before_canonical,
                    new_values=after_canonical,
                    details={
                        "old_source_values": [
                            json.loads(value) for value in before_source_values
                        ],
                        "new_source_values": [
                            json.loads(value) for value in after_source_values
                        ],
                    },
                )

            if not before_conflict and after_conflict:
                summary["changes_created"] += _insert_change_event(
                    connection,
                    observation=observation,
                    policy=policy,
                    event_type="fact.conflict_detected",
                    old_values=before_canonical,
                    new_values=after_canonical,
                    details={"conflict_resolution": "require_review"},
                )
            elif before_conflict and not after_conflict:
                summary["changes_created"] += _insert_change_event(
                    connection,
                    observation=observation,
                    policy=policy,
                    event_type="fact.conflict_resolved",
                    old_values=before_canonical,
                    new_values=after_canonical,
                    details={"conflict_resolution": "require_review"},
                )
    return summary


def list_current_facts(
    database_path: Path,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    predicate: str | None = None,
) -> list[dict[str, object]]:
    create_database(database_path)
    clauses = ["fact.valid_to IS NULL", "fact.status IN ('current', 'conflicted')"]
    parameters: list[object] = []
    for column, value in (
        ("fact.subject_type", subject_type),
        ("fact.subject_id", subject_id),
        ("fact.predicate", predicate),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT fact.*
            FROM facts AS fact
            WHERE {' AND '.join(clauses)}
            ORDER BY fact.subject_type, fact.subject_id,
                     fact.predicate, fact.display_value
            """,
            parameters,
        ).fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["value"] = json.loads(str(item.pop("normalized_value_json")))
            item["sources"] = [
                str(source_row["source"])
                for source_row in connection.execute(
                    """
                    SELECT DISTINCT source
                    FROM fact_evidence
                    WHERE fact_id = ? AND is_current = 1
                    ORDER BY source
                    """,
                    (item["fact_id"],),
                ).fetchall()
            ]
            results.append(item)
    return results


def list_change_events(
    database_path: Path,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    event_type: str | None = None,
) -> list[dict[str, object]]:
    create_database(database_path)
    clauses = ["1 = 1"]
    parameters: list[object] = []
    for column, value in (
        ("subject_type", subject_type),
        ("subject_id", subject_id),
        ("event_type", event_type),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT *
            FROM change_events
            WHERE {' AND '.join(clauses)}
            ORDER BY detected_at, event_id
            """,
            parameters,
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["old_value"] = json.loads(str(item.pop("old_value_json")))
        item["new_value"] = json.loads(str(item.pop("new_value_json")))
        item["details"] = json.loads(str(item.pop("details_json")))
        item["review_required"] = bool(item["review_required"])
        results.append(item)
    return results


def _observed_values(
    predicate: str,
    values: Iterable[Any],
) -> list[ObservedFactValue]:
    observed: list[ObservedFactValue] = []
    for value in values:
        normalized_json = json.dumps(
            _normalize_value(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        locator_suffix = hashlib.sha256(
            normalized_json.encode("utf-8")
        ).hexdigest()[:12]
        observed.append(
            ObservedFactValue(
                value=value,
                source_locator=f"{predicate}[{locator_suffix}]",
            )
        )
    return observed


def _fact_set(
    *,
    subject_type: str,
    subject_id: str,
    predicate: str,
    values: Iterable[Any],
    source: str,
    source_record_id: str,
    observed_at: str,
    source_url: str,
    snapshot_id: str | None,
    extractor: str,
) -> FactObservationSet:
    return FactObservationSet(
        subject_type=subject_type,
        subject_id=subject_id,
        predicate=predicate,
        values=_observed_values(predicate, values),
        source=source,
        source_record_id=source_record_id,
        observed_at=observed_at,
        source_url=source_url,
        snapshot_id=snapshot_id,
        extractor=extractor,
    )


def adc_seed_fact_sets(
    record: ADCRecord,
    *,
    observed_at: str,
) -> list[FactObservationSet]:
    fields: dict[str, list[Any]] = {
        "adc.target": [record.target] if record.target else [],
        "adc.antibody": [record.antibody] if record.antibody else [],
        "adc.linker_name": [record.linker_name] if record.linker_name else [],
        "adc.linker_type": (
            [record.linker_type.value]
            if record.linker_type.value != "unknown"
            else []
        ),
        "adc.payload_name": [record.payload_name] if record.payload_name else [],
        "adc.payload_class": [record.payload_class] if record.payload_class else [],
        "adc.dar": [record.dar] if record.dar is not None else [],
        "adc.indication": [record.indication] if record.indication else [],
        "adc.development_status": [record.development_status.value],
        "adc.company": [record.company] if record.company else [],
    }
    return [
        _fact_set(
            subject_type="adc",
            subject_id=record.adc_id,
            predicate=predicate,
            values=values,
            source="curated_seed",
            source_record_id=record.adc_id,
            observed_at=observed_at,
            source_url=record.source_url or "public-seed",
            snapshot_id=None,
            extractor="curated_seed_v1",
        )
        for predicate, values in fields.items()
    ]


def adcdb_fact_sets(
    record: ADCdbRecord,
    adc_id: str,
    *,
    observed_at: str,
    snapshot_id: str,
    normalizer: EntityNormalizer,
) -> list[FactObservationSet]:
    target = normalizer.canonical_target(record.antigen_name or "")
    normalized_status = normalize_text(record.drug_status or "")
    if "approved" in normalized_status:
        development_status = "approved"
    elif any(
        term in normalized_status
        for term in ("discontinued", "withdrawn", "terminated")
    ):
        development_status = "discontinued"
    elif normalized_status:
        development_status = "investigational"
    else:
        development_status = None
    fields: dict[str, list[Any]] = {
        "adc.target": [target] if target else [],
        "adc.antibody": [record.antibody_name] if record.antibody_name else [],
        "adc.linker_name": [record.linker_name] if record.linker_name else [],
        "adc.payload_name": [record.payload_name] if record.payload_name else [],
        "adc.dar": [record.dar] if record.dar is not None else [],
        "adc.indication": (
            [record.representative_indication]
            if record.representative_indication
            else []
        ),
        "adc.development_status": (
            [development_status] if development_status else []
        ),
        "adc.company": [record.organization] if record.organization else [],
    }
    return [
        _fact_set(
            subject_type="adc",
            subject_id=adc_id,
            predicate=predicate,
            values=values,
            source="adcdb",
            source_record_id=record.adcdb_id,
            observed_at=observed_at,
            source_url=record.detail_url,
            snapshot_id=snapshot_id,
            extractor="adcdb_structured_v1",
        )
        for predicate, values in fields.items()
    ]


def trial_fact_sets(
    record: TrialRecord,
    *,
    observed_at: str,
    snapshot_id: str,
) -> list[FactObservationSet]:
    fields: dict[str, list[Any]] = {
        "trial.overall_status": (
            [record.overall_status] if record.overall_status else []
        ),
        "trial.phases": record.phases,
        "trial.conditions": record.conditions,
        "trial.interventions": [
            {"name": intervention} for intervention in record.interventions
        ],
        "trial.primary_outcomes": [
            {"measure": outcome} for outcome in record.primary_outcomes
        ],
        "trial.enrollment": (
            [record.enrollment] if record.enrollment is not None else []
        ),
        "trial.start_date": [record.start_date] if record.start_date else [],
        "trial.completion_date": (
            [record.completion_date] if record.completion_date else []
        ),
    }
    return [
        _fact_set(
            subject_type="trial",
            subject_id=record.nct_id,
            predicate=predicate,
            values=values,
            source="clinicaltrials",
            source_record_id=record.nct_id,
            observed_at=observed_at,
            source_url=record.source_url,
            snapshot_id=snapshot_id,
            extractor="clinicaltrials_structured_v1",
        )
        for predicate, values in fields.items()
    ]


def publication_fact_sets(
    record: DocumentRecord,
    *,
    observed_at: str,
    snapshot_id: str,
) -> list[FactObservationSet]:
    fields: dict[str, list[Any]] = {
        "publication.title": [record.title],
        "publication.abstract": [record.abstract] if record.abstract else [],
        "publication.publication_date": (
            [record.publication_date] if record.publication_date else []
        ),
        "publication.publication_type": [],
    }
    return [
        _fact_set(
            subject_type="publication",
            subject_id=record.source_record_id,
            predicate=predicate,
            values=values,
            source="pubmed",
            source_record_id=record.source_record_id,
            observed_at=observed_at,
            source_url=record.source_url,
            snapshot_id=snapshot_id,
            extractor="pubmed_structured_v1",
        )
        for predicate, values in fields.items()
    ]
