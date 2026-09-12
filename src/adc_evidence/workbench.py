from __future__ import annotations

import csv
import hashlib
import io
import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from adc_evidence.config import DEFAULT_DATABASE_PATH, DEFAULT_SEED_PATH
from adc_evidence.database import (
    SCHEMA_VERSION,
    connect,
    create_database,
    initialize_database,
    load_seed_records,
)
from adc_evidence.evidence_policy import EvidencePolicy, load_evidence_policy
from adc_evidence.facts import adc_seed_fact_sets, record_fact_sets
from adc_evidence.rag.documents import retrieval_corpus_version


EVIDENCE_BRIEF_SCHEMA_VERSION = "0.6-evidence-brief-v1"
EVIDENCE_DISCLAIMER = (
    "本报告用于公开信息核查与研发情报辅助，不构成科研定论、临床建议、监管意见或投资建议。"
    "字段可能缺失、过期或存在来源冲突；使用前应打开原始来源并由合格人员复核。"
)

ADC_FIELD_SPECS: tuple[tuple[str, str], ...] = (
    ("adc.target", "靶点"),
    ("adc.antibody", "抗体"),
    ("adc.linker_name", "Linker"),
    ("adc.linker_type", "Linker 类型"),
    ("adc.payload_name", "Payload"),
    ("adc.payload_class", "Payload 类型"),
    ("adc.dar", "DAR"),
    ("adc.indication", "适应证"),
    ("adc.development_status", "研发状态"),
    ("adc.company", "企业"),
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _parse_timestamp(value: object | None) -> datetime | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def _display_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _review_status(values: Iterable[str]) -> str:
    statuses = sorted(set(values))
    if not statuses:
        return "not_applicable"
    if len(statuses) == 1:
        return statuses[0]
    if "needs_review" in statuses:
        return "needs_review"
    return "mixed"


def sync_public_seed_facts(
    database_path: Path = DEFAULT_DATABASE_PATH,
    seed_path: Path = DEFAULT_SEED_PATH,
    *,
    observed_at: str | None = None,
) -> dict[str, int]:
    """Ensure the public demo seed also exists in the temporal fact layer."""
    initialize_database(database_path, seed_path)
    records = load_seed_records(seed_path)
    timestamp = observed_at or datetime.now(UTC).replace(microsecond=0).isoformat()
    summary = record_fact_sets(
        database_path,
        [
            fact_set
            for record in records
            for fact_set in adc_seed_fact_sets(record, observed_at=timestamp)
        ],
    )
    return {"adc_count": len(records), **summary}


def evidence_data_version(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> dict[str, object]:
    """Create a deterministic version for all evidence-workbench inputs."""
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        schema_versions = [
            str(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_versions ORDER BY version"
            ).fetchall()
        ]
        latest_run = connection.execute(
            """
            SELECT run_id, finished_at, status
            FROM ingestion_runs
            WHERE finished_at IS NOT NULL
            ORDER BY finished_at DESC, run_id DESC
            LIMIT 1
            """
        ).fetchone()
        table_rows: dict[str, list[tuple[object, ...]]] = {}
        queries = {
            "adcs": (
                "SELECT adc_id, adc_name, target, antibody, linker_name, "
                "linker_type, payload_name, payload_class, dar, indication, "
                "development_status, company, source_url, data_review_status "
                "FROM adcs ORDER BY adc_id"
            ),
            "aliases": (
                "SELECT adc_id, alias FROM adc_aliases ORDER BY adc_id, alias"
            ),
            "facts": (
                "SELECT fact_id, content_hash, status, valid_from, valid_to, "
                "review_status, policy_version FROM facts ORDER BY fact_id"
            ),
            "fact_evidence": (
                "SELECT fact_evidence_id, content_hash, is_current, valid_to, "
                "review_status, observed_at FROM fact_evidence "
                "ORDER BY fact_evidence_id"
            ),
            "change_events": (
                "SELECT event_id, content_hash, review_status FROM change_events "
                "ORDER BY event_id"
            ),
            "trials": (
                "SELECT nct_id, overall_status, phases_json, conditions_json, "
                "interventions_json, enrollment, start_date, completion_date, "
                "primary_outcomes_json, checksum FROM trials ORDER BY nct_id"
            ),
            "documents": (
                "SELECT document_id, source, source_record_id, publication_date, "
                "checksum FROM documents ORDER BY document_id"
            ),
            "entity_links": (
                "SELECT entity_type, entity_id, source_record_type, "
                "source_record_id, matched_alias, match_method FROM entity_links "
                "ORDER BY entity_type, entity_id, source_record_type, source_record_id"
            ),
        }
        for name, query in queries.items():
            table_rows[name] = [
                tuple(row) for row in connection.execute(query).fetchall()
            ]
        chunk_count = int(
            connection.execute("SELECT COUNT(*) FROM text_chunks").fetchone()[0]
        )
    corpus_version = (
        retrieval_corpus_version(database_path) if chunk_count else None
    )
    policy_version = load_evidence_policy().policy_version
    latest_run_payload = (
        None
        if latest_run is None
        else {
            "run_id": str(latest_run["run_id"]),
            "finished_at": str(latest_run["finished_at"]),
            "status": str(latest_run["status"]),
        }
    )
    payload = {
        "schema_versions": schema_versions,
        "policy_version": policy_version,
        "latest_ingestion_run": latest_run_payload,
        "retrieval_corpus_version": corpus_version,
        "tables": table_rows,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return {
        "data_version": f"data_{digest}",
        "schema_version": SCHEMA_VERSION,
        "schema_versions": schema_versions,
        "policy_version": policy_version,
        "latest_ingestion_run": latest_run_payload,
        "retrieval_corpus_version": corpus_version,
    }


def _freshness(
    *,
    source: str,
    observed_at: object | None,
    fetched_at: object | None,
    policy: EvidencePolicy,
    now: datetime,
) -> dict[str, object]:
    source_policy = policy.sources.get(source)
    reference = _parse_timestamp(fetched_at) or _parse_timestamp(observed_at)
    max_age = source_policy.max_age_hours if source_policy else None
    if max_age is None:
        status = "demo_source" if source == "curated_seed" else "not_applicable"
        age_hours = None if reference is None else max(
            0.0,
            round((now - reference).total_seconds() / 3600, 2),
        )
        is_stale: bool | None = None
    elif reference is None:
        status = "unknown"
        age_hours = None
        is_stale = None
    else:
        age_hours = max(0.0, round((now - reference).total_seconds() / 3600, 2))
        is_stale = age_hours > max_age
        status = "stale" if is_stale else "current"
    return {
        "status": status,
        "age_hours": age_hours,
        "max_age_hours": max_age,
        "is_stale": is_stale,
    }


def _fact_query(active: bool) -> str:
    state_clause = (
        "fact.valid_to IS NULL AND fact.status IN ('current', 'conflicted')"
        if active
        else "(fact.valid_to IS NOT NULL OR fact.status = 'superseded')"
    )
    evidence_clause = "AND evidence.is_current = 1" if active else ""
    return f"""
        SELECT
            fact.fact_id, fact.predicate, fact.normalized_value_json,
            fact.display_value, fact.value_type, fact.status AS fact_status,
            fact.valid_from, fact.valid_to,
            fact.review_status AS fact_review_status,
            fact.policy_version, fact.content_hash AS fact_content_hash,
            evidence.fact_evidence_id, evidence.snapshot_id,
            evidence.source, evidence.source_record_id,
            evidence.source_locator, evidence.evidence_text,
            evidence.source_url, evidence.confidence,
            evidence.extractor, evidence.observed_at,
            evidence.valid_to AS evidence_valid_to,
            evidence.is_current,
            evidence.review_status AS evidence_review_status,
            snapshot.fetched_at, snapshot.source_updated_at,
            snapshot.dataset_version, snapshot.parser_version
        FROM facts AS fact
        LEFT JOIN fact_evidence AS evidence
          ON evidence.fact_id = fact.fact_id {evidence_clause}
        LEFT JOIN source_snapshots AS snapshot
          ON snapshot.snapshot_id = evidence.snapshot_id
        WHERE fact.subject_type = 'adc'
          AND fact.subject_id = ?
          AND {state_clause}
        ORDER BY fact.predicate, fact.display_value,
                 evidence.source, evidence.observed_at
    """


def _group_fact_rows(
    rows,
    *,
    policy: EvidencePolicy,
    now: datetime,
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    for row in rows:
        fact_id = str(row["fact_id"])
        fact = grouped.get(fact_id)
        if fact is None:
            fact = {
                "fact_id": fact_id,
                "predicate": str(row["predicate"]),
                "value": json.loads(str(row["normalized_value_json"])),
                "display_value": str(row["display_value"]),
                "value_type": str(row["value_type"]),
                "status": str(row["fact_status"]),
                "valid_from": str(row["valid_from"]),
                "valid_to": (
                    str(row["valid_to"]) if row["valid_to"] is not None else None
                ),
                "review_status": str(row["fact_review_status"]),
                "policy_version": str(row["policy_version"]),
                "content_hash": str(row["fact_content_hash"]),
                "evidence": [],
            }
            grouped[fact_id] = fact
        if row["fact_evidence_id"] is None:
            continue
        source = str(row["source"])
        freshness = _freshness(
            source=source,
            observed_at=row["observed_at"],
            fetched_at=row["fetched_at"],
            policy=policy,
            now=now,
        )
        fact["evidence"].append(
            {
                "fact_evidence_id": str(row["fact_evidence_id"]),
                "snapshot_id": (
                    str(row["snapshot_id"])
                    if row["snapshot_id"] is not None
                    else None
                ),
                "source": source,
                "source_display_name": (
                    policy.sources[source].display_name
                    if source in policy.sources
                    else source
                ),
                "source_record_id": str(row["source_record_id"]),
                "source_locator": str(row["source_locator"]),
                "evidence_text": str(row["evidence_text"]),
                "source_url": str(row["source_url"]),
                "confidence": float(row["confidence"]),
                "extractor": str(row["extractor"]),
                "observed_at": str(row["observed_at"]),
                "fetched_at": (
                    str(row["fetched_at"])
                    if row["fetched_at"] is not None
                    else None
                ),
                "source_updated_at": (
                    str(row["source_updated_at"])
                    if row["source_updated_at"] is not None
                    else None
                ),
                "dataset_version": (
                    str(row["dataset_version"])
                    if row["dataset_version"] is not None
                    else None
                ),
                "parser_version": (
                    str(row["parser_version"])
                    if row["parser_version"] is not None
                    else None
                ),
                "valid_to": (
                    str(row["evidence_valid_to"])
                    if row["evidence_valid_to"] is not None
                    else None
                ),
                "is_current": bool(row["is_current"]),
                "review_status": str(row["evidence_review_status"]),
                "freshness": freshness,
            }
        )
    return list(grouped.values())


def _field_payload(
    predicate: str,
    label: str,
    current_facts: list[dict[str, object]],
    history_facts: list[dict[str, object]],
) -> dict[str, object]:
    values = [item for item in current_facts if item["predicate"] == predicate]
    history = [item for item in history_facts if item["predicate"] == predicate]
    evidence = [entry for item in values for entry in item["evidence"]]
    sources = sorted({str(entry["source"]) for entry in evidence})
    conflict = any(item["status"] == "conflicted" for item in values)
    stale = any(
        entry["freshness"]["is_stale"] is True
        for entry in evidence
    )
    external_evidence = [
        entry for entry in evidence if entry["source"] != "curated_seed"
    ]
    if not values:
        status = "missing"
        freshness_status = "unknown"
    elif conflict:
        status = "conflicted"
        freshness_status = "stale" if stale else "mixed"
    else:
        status = "current"
        if stale:
            freshness_status = "stale"
        elif not external_evidence:
            freshness_status = "demo_source"
        elif any(
            entry["freshness"]["status"] == "unknown"
            for entry in external_evidence
        ):
            freshness_status = "unknown"
        else:
            freshness_status = "current"
    observed_values = [str(entry["observed_at"]) for entry in evidence]
    review_values = [
        str(item["review_status"]) for item in values
    ] + [str(entry["review_status"]) for entry in evidence]
    return {
        "predicate": predicate,
        "label": label,
        "status": status,
        "is_missing": not values,
        "is_conflicted": conflict,
        "freshness_status": freshness_status,
        "is_stale": stale,
        "review_status": _review_status(review_values),
        "display_value": "；".join(
            str(item["display_value"]) for item in values
        ) if values else "未记录",
        "values": values,
        "sources": sources,
        "evidence_count": len(evidence),
        "latest_observed_at": max(observed_values) if observed_values else None,
        "traceability_complete": bool(values) and bool(evidence) and all(
            entry.get("source_record_id")
            and entry.get("source_url")
            and entry.get("observed_at")
            and entry.get("review_status")
            for entry in evidence
        ),
        "history": history,
    }


def get_adc_evidence_card(
    database_path: Path,
    adc_id: str,
    *,
    now: datetime | None = None,
    data_version: dict[str, object] | None = None,
) -> dict[str, object]:
    """Return one ADC card with field values, provenance, history and warnings."""
    create_database(database_path)
    policy = load_evidence_policy()
    current_time = _now(now)
    with closing(connect(database_path)) as connection:
        adc = connection.execute(
            "SELECT * FROM adcs WHERE adc_id = ?",
            (adc_id,),
        ).fetchone()
        if adc is None:
            raise LookupError(f"Unknown ADC: {adc_id}")
        aliases = [
            str(row[0])
            for row in connection.execute(
                "SELECT alias FROM adc_aliases WHERE adc_id = ? ORDER BY alias",
                (adc_id,),
            ).fetchall()
        ]
        current_rows = connection.execute(_fact_query(True), (adc_id,)).fetchall()
        history_rows = connection.execute(_fact_query(False), (adc_id,)).fetchall()
    current_facts = _group_fact_rows(
        current_rows,
        policy=policy,
        now=current_time,
    )
    history_facts = _group_fact_rows(
        history_rows,
        policy=policy,
        now=current_time,
    )
    fields = [
        _field_payload(predicate, label, current_facts, history_facts)
        for predicate, label in ADC_FIELD_SPECS
    ]
    missing_fields = [str(field["predicate"]) for field in fields if field["is_missing"]]
    conflicted_fields = [
        str(field["predicate"]) for field in fields if field["is_conflicted"]
    ]
    stale_fields = [str(field["predicate"]) for field in fields if field["is_stale"]]
    return {
        "adc_id": adc_id,
        "adc_name": str(adc["adc_name"]),
        "aliases": aliases,
        "legacy_target": str(adc["target"]),
        "legacy_review_status": str(adc["data_review_status"]),
        "fields": fields,
        "field_map": {str(field["predicate"]): field for field in fields},
        "missing_fields": missing_fields,
        "conflicted_fields": conflicted_fields,
        "stale_fields": stale_fields,
        "traceability_complete": all(
            bool(field["traceability_complete"])
            for field in fields
            if not bool(field["is_missing"])
        ),
        "generated_at": current_time.isoformat(),
        "data_version": data_version or evidence_data_version(database_path),
        "disclaimer": EVIDENCE_DISCLAIMER,
    }


def compare_adcs(
    database_path: Path,
    adc_ids: Iterable[str],
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    selected_ids = list(dict.fromkeys(str(item) for item in adc_ids))
    if not 2 <= len(selected_ids) <= 10:
        raise ValueError("ADC comparison requires 2 to 10 unique ADC IDs")
    current_time = _now(now)
    version = evidence_data_version(database_path)
    cards = [
        get_adc_evidence_card(
            database_path,
            adc_id,
            now=current_time,
            data_version=version,
        )
        for adc_id in selected_ids
    ]
    rows: list[dict[str, object]] = []
    for predicate, label in ADC_FIELD_SPECS:
        cells: dict[str, dict[str, object]] = {}
        for card in cards:
            field = dict(card["field_map"])[predicate]
            cells[str(card["adc_id"])] = {
                "display_value": field["display_value"],
                "status": field["status"],
                "freshness_status": field["freshness_status"],
                "review_status": field["review_status"],
                "sources": field["sources"],
                "latest_observed_at": field["latest_observed_at"],
                "evidence_count": field["evidence_count"],
                "traceability_complete": field["traceability_complete"],
                "values": field["values"],
            }
        rows.append({"predicate": predicate, "label": label, "cells": cells})
    return {
        "adc_ids": selected_ids,
        "adcs": [
            {
                "adc_id": card["adc_id"],
                "adc_name": card["adc_name"],
                "aliases": card["aliases"],
            }
            for card in cards
        ],
        "rows": rows,
        "cards": cards,
        "generated_at": current_time.isoformat(),
        "data_version": version,
        "traceability_complete": all(
            bool(cell["traceability_complete"])
            for row in rows
            for cell in dict(row["cells"]).values()
            if cell["status"] != "missing"
        ),
        "disclaimer": EVIDENCE_DISCLAIMER,
    }


def comparison_to_csv(comparison: dict[str, object]) -> bytes:
    output = io.StringIO(newline="")
    adcs = list(comparison["adcs"])
    version = dict(comparison["data_version"])
    fieldnames = [
        "data_version",
        "schema_version",
        "policy_version",
        "generated_at",
        "predicate",
        "field_label",
    ]
    for adc in adcs:
        prefix = str(adc["adc_id"])
        fieldnames.extend(
            (
                f"{prefix}_name",
                f"{prefix}_value",
                f"{prefix}_status",
                f"{prefix}_freshness",
                f"{prefix}_review_status",
                f"{prefix}_sources",
                f"{prefix}_observed_at",
            )
        )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for comparison_row in comparison["rows"]:
        row = {
            "data_version": version["data_version"],
            "schema_version": version["schema_version"],
            "policy_version": version["policy_version"],
            "generated_at": comparison["generated_at"],
            "predicate": comparison_row["predicate"],
            "field_label": comparison_row["label"],
        }
        cells = dict(comparison_row["cells"])
        for adc in adcs:
            prefix = str(adc["adc_id"])
            cell = cells[prefix]
            row.update(
                {
                    f"{prefix}_name": adc["adc_name"],
                    f"{prefix}_value": cell["display_value"],
                    f"{prefix}_status": cell["status"],
                    f"{prefix}_freshness": cell["freshness_status"],
                    f"{prefix}_review_status": cell["review_status"],
                    f"{prefix}_sources": " | ".join(cell["sources"]),
                    f"{prefix}_observed_at": cell["latest_observed_at"] or "",
                }
            )
        writer.writerow(row)
    return output.getvalue().encode("utf-8-sig")


def _markdown_escape(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def comparison_to_markdown(comparison: dict[str, object]) -> str:
    adcs = list(comparison["adcs"])
    version = dict(comparison["data_version"])
    lines = [
        "# ADC 结构化证据比较",
        "",
        f"- 生成时间：{comparison['generated_at']}",
        f"- 数据版本：`{version['data_version']}`",
        f"- 数据库模式：`{version['schema_version']}`",
        f"- 证据策略：`{version['policy_version']}`",
        "",
        "| 字段 | " + " | ".join(_markdown_escape(adc["adc_name"]) for adc in adcs) + " |",
        "|---|" + "---|" * len(adcs),
    ]
    for row in comparison["rows"]:
        cells = dict(row["cells"])
        values = []
        for adc in adcs:
            cell = cells[str(adc["adc_id"])]
            suffix = "（冲突）" if cell["status"] == "conflicted" else ""
            values.append(_markdown_escape(f"{cell['display_value']}{suffix}"))
        lines.append(
            f"| {_markdown_escape(row['label'])} | " + " | ".join(values) + " |"
        )
    lines.extend(("", "## 单元格证据", ""))
    for row in comparison["rows"]:
        cells = dict(row["cells"])
        for adc in adcs:
            cell = cells[str(adc["adc_id"])]
            if cell["status"] == "missing":
                continue
            lines.append(f"### {adc['adc_name']} · {row['label']}")
            lines.append("")
            for value in cell["values"]:
                for evidence in value["evidence"]:
                    lines.append(
                        f"- {evidence['source_display_name']} / "
                        f"{evidence['source_record_id']}；观测：{evidence['observed_at']}；"
                        f"审核：{evidence['review_status']}；[原始来源]({evidence['source_url']})"
                    )
            lines.append("")
    lines.extend(("## 免责声明", "", str(comparison["disclaimer"]), ""))
    return "\n".join(lines)


def _event_entities(connection, event) -> dict[str, list[str]]:
    subject_type = str(event["subject_type"])
    subject_id = str(event["subject_id"])
    adc_ids: set[str] = set()
    targets: set[str] = set()
    if subject_type == "adc":
        adc_ids.add(subject_id)
    elif subject_type == "target":
        targets.add(subject_id)
    elif subject_type == "trial":
        rows = connection.execute(
            """
            SELECT entity_type, entity_id FROM entity_links
            WHERE source_record_type = 'trial' AND source_record_id = ?
            """,
            (subject_id,),
        ).fetchall()
        for row in rows:
            if row["entity_type"] == "adc":
                adc_ids.add(str(row["entity_id"]))
            elif row["entity_type"] == "target":
                targets.add(str(row["entity_id"]))
    elif subject_type == "publication":
        document_ids = [
            str(row[0])
            for row in connection.execute(
                """
                SELECT document_id FROM documents
                WHERE source_record_id = ? OR document_id = ?
                """,
                (subject_id, subject_id),
            ).fetchall()
        ]
        for document_id in document_ids:
            rows = connection.execute(
                """
                SELECT entity_type, entity_id FROM entity_links
                WHERE source_record_type = 'document' AND source_record_id = ?
                """,
                (document_id,),
            ).fetchall()
            for row in rows:
                if row["entity_type"] == "adc":
                    adc_ids.add(str(row["entity_id"]))
                elif row["entity_type"] == "target":
                    targets.add(str(row["entity_id"]))
    elif subject_type == "source_record" and event["source"] == "adcdb":
        rows = connection.execute(
            """
            SELECT entity_id FROM external_identifiers
            WHERE entity_type = 'adc' AND source = 'adcdb'
              AND external_id = ?
            """,
            (event["source_record_id"],),
        ).fetchall()
        adc_ids.update(str(row[0]) for row in rows)
    if adc_ids:
        placeholders = ",".join("?" for _ in adc_ids)
        targets.update(
            str(row[0])
            for row in connection.execute(
                f"SELECT target FROM adcs WHERE adc_id IN ({placeholders})",
                sorted(adc_ids),
            ).fetchall()
        )
    adc_names: list[str] = []
    if adc_ids:
        placeholders = ",".join("?" for _ in adc_ids)
        adc_names = [
            str(row[0])
            for row in connection.execute(
                f"SELECT adc_name FROM adcs WHERE adc_id IN ({placeholders}) "
                "ORDER BY adc_name",
                sorted(adc_ids),
            ).fetchall()
        ]
    return {
        "adc_ids": sorted(adc_ids),
        "adc_names": adc_names,
        "targets": sorted(targets),
    }


def list_changes(
    database_path: Path,
    *,
    days: int,
    adc_ids: Iterable[str] = (),
    targets: Iterable[str] = (),
    sources: Iterable[str] = (),
    event_types: Iterable[str] = (),
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """List recent events enriched with ADC and target filters."""
    if days not in {1, 7, 30}:
        raise ValueError("days must be one of 1, 7 or 30")
    current_time = _now(now)
    cutoff = current_time - timedelta(days=days)
    adc_filter = set(adc_ids)
    target_filter = {str(item).casefold() for item in targets}
    source_filter = set(sources)
    event_filter = set(event_types)
    create_database(database_path)
    results: list[dict[str, object]] = []
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM change_events ORDER BY detected_at DESC, event_id DESC"
        ).fetchall()
        for row in rows:
            detected = _parse_timestamp(row["detected_at"])
            if detected is None or detected < cutoff or detected > current_time:
                continue
            if source_filter and str(row["source"] or "") not in source_filter:
                continue
            if event_filter and str(row["event_type"]) not in event_filter:
                continue
            entities = _event_entities(connection, row)
            if adc_filter and not adc_filter.intersection(entities["adc_ids"]):
                continue
            if target_filter and not target_filter.intersection(
                target.casefold() for target in entities["targets"]
            ):
                continue
            snapshot = None
            if row["snapshot_id"] is not None:
                snapshot_row = connection.execute(
                    """
                    SELECT fetched_at, source_updated_at, source_url,
                           content_hash, dataset_version, parser_version
                    FROM source_snapshots WHERE snapshot_id = ?
                    """,
                    (row["snapshot_id"],),
                ).fetchone()
                snapshot = dict(snapshot_row) if snapshot_row is not None else None
            results.append(
                {
                    **dict(row),
                    "old_value": json.loads(str(row["old_value_json"])),
                    "new_value": json.loads(str(row["new_value_json"])),
                    "details": json.loads(str(row["details_json"])),
                    "review_required": bool(row["review_required"]),
                    "entities": entities,
                    "snapshot": snapshot,
                }
            )
    return results


def build_evidence_brief(
    database_path: Path,
    adc_ids: Iterable[str],
    *,
    generated_at: datetime | None = None,
) -> dict[str, object]:
    selected_ids = list(dict.fromkeys(str(item) for item in adc_ids))
    if not 1 <= len(selected_ids) <= 10:
        raise ValueError("Evidence Brief requires 1 to 10 unique ADC IDs")
    current_time = _now(generated_at)
    version = evidence_data_version(database_path)
    cards = []
    for adc_id in selected_ids:
        card = get_adc_evidence_card(
            database_path,
            adc_id,
            now=current_time,
            data_version=version,
        )
        card.pop("field_map", None)
        cards.append(card)
    generated_at_text = current_time.isoformat()
    brief_hash = hashlib.sha256(
        _canonical_json(
            {
                "data_version": version["data_version"],
                "adc_ids": selected_ids,
                "generated_at": generated_at_text,
            }
        ).encode("utf-8")
    ).hexdigest()
    return {
        "brief_schema_version": EVIDENCE_BRIEF_SCHEMA_VERSION,
        "brief_id": f"brief_{brief_hash[:24]}",
        "generated_at": generated_at_text,
        "data_version": version,
        "scope": {
            "adc_ids": selected_ids,
            "adc_names": [str(card["adc_name"]) for card in cards],
        },
        "cards": cards,
        "evidence_count": sum(
            int(field["evidence_count"])
            for card in cards
            for field in card["fields"]
        ),
        "disclaimer": EVIDENCE_DISCLAIMER,
    }


def evidence_brief_to_json(brief: dict[str, object]) -> bytes:
    return (
        json.dumps(brief, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def evidence_brief_to_markdown(brief: dict[str, object]) -> str:
    version = dict(brief["data_version"])
    lines = [
        "# ADC Evidence Brief",
        "",
        f"- Brief ID：`{brief['brief_id']}`",
        f"- 生成时间：{brief['generated_at']}",
        f"- 数据版本：`{version['data_version']}`",
        f"- 数据库模式：`{version['schema_version']}`",
        f"- 证据策略：`{version['policy_version']}`",
        f"- 检索语料版本：`{version['retrieval_corpus_version'] or '未构建'}`",
        "",
    ]
    for card in brief["cards"]:
        lines.extend(
            (
                f"## {card['adc_name']} (`{card['adc_id']}`)",
                "",
                "| 字段 | 当前值 | 状态 | 新鲜度 | 审核状态 | 来源 |",
                "|---|---|---|---|---|---|",
            )
        )
        for field in card["fields"]:
            lines.append(
                "| "
                + " | ".join(
                    _markdown_escape(value)
                    for value in (
                        field["label"],
                        field["display_value"],
                        field["status"],
                        field["freshness_status"],
                        field["review_status"],
                        ", ".join(field["sources"]) or "无",
                    )
                )
                + " |"
            )
        lines.extend(("", "### 字段级证据", ""))
        for field in card["fields"]:
            if field["is_missing"]:
                continue
            lines.append(f"#### {field['label']}：{field['display_value']}")
            lines.append("")
            for value in field["values"]:
                for evidence in value["evidence"]:
                    lines.append(
                        f"- **{evidence['source_display_name']}** / "
                        f"`{evidence['source_record_id']}`；观测时间："
                        f"{evidence['observed_at']}；来源更新时间："
                        f"{evidence['source_updated_at'] or '未提供'}；审核："
                        f"{evidence['review_status']}；[打开来源]({evidence['source_url']})"
                    )
                    lines.append(f"  - 证据：{evidence['evidence_text']}")
            if field["history"]:
                lines.append(
                    "- 历史值："
                    + "；".join(
                        f"{item['display_value']} ({item['valid_from']} → "
                        f"{item['valid_to'] or '未关闭'})"
                        for item in field["history"]
                    )
                )
            lines.append("")
    lines.extend(("## 免责声明", "", str(brief["disclaimer"]), ""))
    return "\n".join(lines)
