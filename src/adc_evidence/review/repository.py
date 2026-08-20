from __future__ import annotations

import hashlib
import json
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adc_evidence.config import DEFAULT_DATABASE_PATH
from adc_evidence.database import connect, create_database


QUESTION_VERDICTS = ("valid", "needs_edit", "invalid")
EVIDENCE_VERDICTS = ("correct", "partial", "incorrect", "not_applicable")
ANSWER_VERDICTS = ("correct", "partial", "incorrect", "not_applicable")
REFUSAL_VERDICTS = ("correct", "incorrect", "not_applicable")
SEVERITIES = ("none", "low", "medium", "high", "critical")
ERROR_CATEGORIES = (
    "retrieval_miss",
    "low_rank",
    "wrong_source",
    "unsupported_claim",
    "missing_citation",
    "invalid_citation",
    "over_refusal",
    "under_refusal",
    "missing_key_fact",
    "scope_guard_error",
    "data_quality",
    "ambiguous_question",
    "system_error",
    "other",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _content_hash(payload: dict[str, object]) -> str:
    encoded = _json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _run_item_id(
    item_type: str,
    question_id: object,
    *,
    explicit_run_id: str,
    variant: str = "",
) -> str:
    if not explicit_run_id:
        return f"{item_type}:{question_id}"
    suffix = f":{variant}" if variant else ""
    return f"{item_type}:{explicit_run_id}{suffix}:{question_id}"


def _decode_row(row: Any) -> dict[str, object]:
    result = dict(row)
    for key in (
        "expected_document_ids_json",
        "system_document_ids_json",
        "metadata_json",
        "error_categories_json",
    ):
        if key in result:
            raw_value = result.pop(key)
            default: object = {} if key == "metadata_json" else []
            result[key.removesuffix("_json")] = (
                json.loads(raw_value) if raw_value is not None else default
            )
    if "expected_refusal" in result:
        result["expected_refusal"] = bool(result["expected_refusal"])
    if result.get("item_content_hash") and result.get("content_hash"):
        result["is_stale"] = result["item_content_hash"] != result["content_hash"]
    return result


def _upsert_item(database_path: Path, item: dict[str, object]) -> None:
    create_database(database_path)
    now = _now()
    payload = {
        key: item[key]
        for key in (
            "item_type",
            "evaluation_run_id",
            "question_id",
            "category",
            "question",
            "expected_refusal",
            "expected_document_ids",
            "system_status",
            "system_output",
            "system_document_ids",
            "backend",
            "model_name",
            "metadata",
        )
    }
    values = {
        **item,
        "expected_refusal": int(bool(item["expected_refusal"])),
        "expected_document_ids_json": _json(item["expected_document_ids"]),
        "system_document_ids_json": _json(item["system_document_ids"]),
        "metadata_json": _json(item["metadata"]),
        "content_hash": _content_hash(payload),
        "created_at": now,
        "updated_at": now,
    }
    with closing(connect(database_path)) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO review_items (
                    item_id, item_type, evaluation_run_id, question_id,
                    category, question,
                    expected_refusal, expected_document_ids_json, system_status,
                    system_output, system_document_ids_json, backend, model_name,
                    metadata_json, content_hash, created_at, updated_at
                ) VALUES (
                    :item_id, :item_type, :evaluation_run_id, :question_id,
                    :category, :question,
                    :expected_refusal, :expected_document_ids_json, :system_status,
                    :system_output, :system_document_ids_json, :backend, :model_name,
                    :metadata_json, :content_hash, :created_at, :updated_at
                )
                ON CONFLICT(item_id) DO UPDATE SET
                    item_type = excluded.item_type,
                    evaluation_run_id = excluded.evaluation_run_id,
                    question_id = excluded.question_id,
                    category = excluded.category,
                    question = excluded.question,
                    expected_refusal = excluded.expected_refusal,
                    expected_document_ids_json = excluded.expected_document_ids_json,
                    system_status = excluded.system_status,
                    system_output = excluded.system_output,
                    system_document_ids_json = excluded.system_document_ids_json,
                    backend = excluded.backend,
                    model_name = excluded.model_name,
                    metadata_json = excluded.metadata_json,
                    content_hash = excluded.content_hash,
                    updated_at = excluded.updated_at
                """,
                values,
            )


def import_generation_report(
    report_path: Path,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> int:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    explicit_run_id = str(report.get("run_id") or "")
    backend = str(report.get("backend", "unknown"))
    evaluation_run_id = explicit_run_id or f"legacy-generation-{backend}"
    default_model = str(
        report.get("requested_model")
        or (
            "deterministic-extractive-v1"
            if backend == "extractive"
            else "unknown"
        )
    )
    for row in report.get("questions", []):
        model_name = str(row.get("model") or default_model)
        metadata = {
            "report_path": str(report_path),
            "run_id": evaluation_run_id,
            "evaluated_at": report.get("evaluated_at"),
            "retrieval_mode": report.get("retrieval_mode"),
            "top_k": report.get("top_k"),
            "refusal_reason": row.get("refusal_reason"),
            "citation_valid": row.get("citation_valid"),
            "gold_citation_hit": row.get("gold_citation_hit"),
            "key_fact_recall": row.get("key_fact_recall"),
            "latency_ms": row.get("latency_ms"),
            "model": model_name,
            "usage": row.get("usage", {}),
            "response_id": row.get("response_id"),
        }
        _upsert_item(
            database_path,
            {
                "item_id": _run_item_id(
                    "generation",
                    row["question_id"],
                    explicit_run_id=explicit_run_id,
                ),
                "item_type": "generation",
                "evaluation_run_id": evaluation_run_id,
                "question_id": str(row["question_id"]),
                "category": str(row["category"]),
                "question": str(row["question"]),
                "expected_refusal": bool(row["should_refuse"]),
                "expected_document_ids": list(row.get("expected_document_ids", [])),
                "system_status": str(row.get("status", "unknown")),
                "system_output": str(row.get("answer", "")),
                "system_document_ids": list(row.get("cited_document_ids", [])),
                "backend": backend,
                "model_name": model_name,
                "metadata": metadata,
            },
        )
    return len(report.get("questions", []))


def import_retrieval_report(
    report_path: Path,
    database_path: Path = DEFAULT_DATABASE_PATH,
    *,
    mode: str = "sparse",
) -> int:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    explicit_run_id = str(report.get("run_id") or "")
    evaluation_run_id = explicit_run_id or f"legacy-retrieval-{mode}"
    result = next(
        (item for item in report.get("results", []) if item.get("mode") == mode),
        None,
    )
    if result is None:
        available = [str(item.get("mode")) for item in report.get("results", [])]
        raise ValueError(f"Retrieval mode {mode!r} not found; available: {available}")

    for row in result.get("questions", []):
        metrics = {
            key: value
            for key, value in row.items()
            if key.startswith("hit_at_") or key in {"reciprocal_rank", "ndcg"}
        }
        retrieved = list(row.get("retrieved_document_ids", []))
        _upsert_item(
            database_path,
            {
                "item_id": _run_item_id(
                    "retrieval",
                    row["question_id"],
                    explicit_run_id=explicit_run_id,
                    variant=mode,
                ),
                "item_type": "retrieval",
                "evaluation_run_id": evaluation_run_id,
                "question_id": str(row["question_id"]),
                "category": str(row["category"]),
                "question": str(row["question"]),
                "expected_refusal": False,
                "expected_document_ids": list(row.get("expected_document_ids", [])),
                "system_status": "retrieved",
                "system_output": "\n".join(retrieved),
                "system_document_ids": retrieved,
                "backend": mode,
                "model_name": (
                    "SQLite FTS5/BM25"
                    if mode == "sparse"
                    else str(result.get("embedding_model") or mode)
                ),
                "metadata": {
                    "report_path": str(report_path),
                    "run_id": evaluation_run_id,
                    "evaluated_at": report.get("evaluated_at"),
                    "top_k": report.get("top_k"),
                    "sparse_weight": result.get("sparse_weight"),
                    "dense_weight": result.get("dense_weight"),
                    **metrics,
                },
            },
        )
    return len(result.get("questions", []))


def prepare_review_queue(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    generation_report_path: Path | None = None,
    retrieval_report_path: Path | None = None,
    retrieval_mode: str = "sparse",
) -> dict[str, int]:
    counts = {"generation": 0, "retrieval": 0}
    if generation_report_path and generation_report_path.exists():
        counts["generation"] = import_generation_report(
            generation_report_path, database_path
        )
    if retrieval_report_path and retrieval_report_path.exists():
        counts["retrieval"] = import_retrieval_report(
            retrieval_report_path, database_path, mode=retrieval_mode
        )
    create_database(database_path)
    return counts


def list_review_items(
    database_path: Path = DEFAULT_DATABASE_PATH,
    *,
    item_type: str | None = None,
    evaluation_run_id: str | None = None,
    status: str = "all",
    reviewer: str = "",
) -> list[dict[str, object]]:
    create_database(database_path)
    clauses: list[str] = []
    parameters: list[object] = []
    if item_type:
        clauses.append("i.item_type = ?")
        parameters.append(item_type)
    if evaluation_run_id:
        clauses.append("i.evaluation_run_id = ?")
        parameters.append(evaluation_run_id)
    reviewer = reviewer.strip()
    if reviewer:
        join = "LEFT JOIN expert_reviews r ON r.item_id = i.item_id AND r.reviewer = ?"
        parameters.insert(0, reviewer)
    else:
        join = "LEFT JOIN expert_reviews r ON r.review_id = (SELECT MAX(r2.review_id) FROM expert_reviews r2 WHERE r2.item_id = i.item_id)"
    if status == "pending":
        clauses.append("r.review_id IS NULL")
    elif status == "reviewed":
        clauses.append("r.review_id IS NOT NULL AND r.item_content_hash = i.content_hash")
    elif status == "stale":
        clauses.append("r.review_id IS NOT NULL AND r.item_content_hash <> i.content_hash")
    elif status != "all":
        raise ValueError(f"Unknown review status: {status}")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT i.*, r.review_id, r.reviewer, r.question_verdict,
               r.evidence_verdict, r.answer_verdict, r.refusal_verdict,
               r.severity, r.error_categories_json, r.notes,
               r.item_content_hash, r.reviewed_at
        FROM review_items i
        {join}
        {where}
        ORDER BY i.item_type, i.category, i.question_id
    """
    with closing(connect(database_path)) as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return [_decode_row(row) for row in rows]


def list_review_runs(
    database_path: Path = DEFAULT_DATABASE_PATH,
    *,
    item_type: str | None = None,
) -> list[dict[str, object]]:
    create_database(database_path)
    where = "WHERE item_type = ?" if item_type else ""
    parameters: tuple[object, ...] = (item_type,) if item_type else ()
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT evaluation_run_id, item_type, backend,
                   GROUP_CONCAT(DISTINCT model_name) AS model_name,
                   COUNT(*) AS item_count, MAX(updated_at) AS updated_at
            FROM review_items
            {where}
            GROUP BY evaluation_run_id, item_type, backend
            ORDER BY MAX(updated_at) DESC, evaluation_run_id
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def get_review_item(
    item_id: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
    *,
    reviewer: str = "",
) -> dict[str, object] | None:
    rows = list_review_items(database_path, reviewer=reviewer)
    return next((row for row in rows if row["item_id"] == item_id), None)


def get_review_documents(
    document_ids: list[str],
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> list[dict[str, object]]:
    if not document_ids:
        return []
    create_database(database_path)
    placeholders = ",".join("?" for _ in document_ids)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT retrieval_document_id, source_type, source_record_id,
                   title, content, source_url, metadata_json
            FROM retrieval_documents
            WHERE retrieval_document_id IN ({placeholders})
            """,
            document_ids,
        ).fetchall()
    by_id = {
        str(row["retrieval_document_id"]): _decode_row(row)
        for row in rows
    }
    return [by_id[document_id] for document_id in document_ids if document_id in by_id]


def save_expert_review(
    *,
    item_id: str,
    reviewer: str,
    question_verdict: str,
    evidence_verdict: str,
    answer_verdict: str,
    refusal_verdict: str,
    severity: str,
    error_categories: list[str],
    notes: str,
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> int:
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("Reviewer name or identifier is required.")
    allowed = {
        "question_verdict": (question_verdict, QUESTION_VERDICTS),
        "evidence_verdict": (evidence_verdict, EVIDENCE_VERDICTS),
        "answer_verdict": (answer_verdict, ANSWER_VERDICTS),
        "refusal_verdict": (refusal_verdict, REFUSAL_VERDICTS),
        "severity": (severity, SEVERITIES),
    }
    for field, (value, choices) in allowed.items():
        if value not in choices:
            raise ValueError(f"Invalid {field}: {value}")
    unknown_categories = sorted(set(error_categories) - set(ERROR_CATEGORIES))
    if unknown_categories:
        raise ValueError(f"Unknown error categories: {unknown_categories}")

    create_database(database_path)
    with closing(connect(database_path)) as connection:
        item = connection.execute(
            "SELECT content_hash FROM review_items WHERE item_id = ?", (item_id,)
        ).fetchone()
        if item is None:
            raise KeyError(f"Unknown review item: {item_id}")
        with connection:
            connection.execute(
                """
                INSERT INTO expert_reviews (
                    item_id, reviewer, question_verdict, evidence_verdict,
                    answer_verdict, refusal_verdict, severity,
                    error_categories_json, notes, item_content_hash, reviewed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(item_id, reviewer) DO UPDATE SET
                    question_verdict = excluded.question_verdict,
                    evidence_verdict = excluded.evidence_verdict,
                    answer_verdict = excluded.answer_verdict,
                    refusal_verdict = excluded.refusal_verdict,
                    severity = excluded.severity,
                    error_categories_json = excluded.error_categories_json,
                    notes = excluded.notes,
                    item_content_hash = excluded.item_content_hash,
                    reviewed_at = excluded.reviewed_at
                """,
                (
                    item_id,
                    reviewer,
                    question_verdict,
                    evidence_verdict,
                    answer_verdict,
                    refusal_verdict,
                    severity,
                    _json(sorted(set(error_categories))),
                    notes.strip(),
                    item["content_hash"],
                    _now(),
                ),
            )
            review_id = connection.execute(
                "SELECT review_id FROM expert_reviews WHERE item_id = ? AND reviewer = ?",
                (item_id, reviewer),
            ).fetchone()[0]
    return int(review_id)


def review_stats(database_path: Path = DEFAULT_DATABASE_PATH) -> dict[str, int]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_items,
                SUM(CASE WHEN current_review.review_id IS NOT NULL
                          AND current_review.item_content_hash = i.content_hash
                         THEN 1 ELSE 0 END) AS reviewed_items,
                SUM(CASE WHEN current_review.review_id IS NOT NULL
                          AND current_review.item_content_hash <> i.content_hash
                         THEN 1 ELSE 0 END) AS stale_items
            FROM review_items i
            LEFT JOIN expert_reviews current_review
              ON current_review.review_id = (
                  SELECT MAX(r2.review_id) FROM expert_reviews r2
                  WHERE r2.item_id = i.item_id
              )
            """
        ).fetchone()
        review_count = connection.execute(
            "SELECT COUNT(*) FROM expert_reviews"
        ).fetchone()[0]
    total = int(row["total_items"] or 0)
    reviewed = int(row["reviewed_items"] or 0)
    return {
        "total_items": total,
        "reviewed_items": reviewed,
        "remaining_items": total - reviewed,
        "stale_items": int(row["stale_items"] or 0),
        "review_count": int(review_count),
    }


def all_expert_reviews(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> list[dict[str, object]]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT i.item_type, i.evaluation_run_id, i.question_id,
                   i.category, i.question, i.backend, i.model_name,
                   i.content_hash, r.*
            FROM expert_reviews r
            JOIN review_items i ON i.item_id = r.item_id
            ORDER BY r.reviewed_at, r.review_id
            """
        ).fetchall()
    return [_decode_row(row) for row in rows]


def review_export_rows(
    database_path: Path = DEFAULT_DATABASE_PATH,
) -> list[dict[str, object]]:
    """Return one flattened row per review, plus one row for every pending item."""
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT i.*, r.review_id, r.reviewer, r.question_verdict,
                   r.evidence_verdict, r.answer_verdict, r.refusal_verdict,
                   r.severity, r.error_categories_json, r.notes,
                   r.item_content_hash, r.reviewed_at
            FROM review_items i
            LEFT JOIN expert_reviews r ON r.item_id = i.item_id
            ORDER BY i.evaluation_run_id, i.item_type, i.question_id,
                     r.reviewed_at, r.review_id
            """
        ).fetchall()
    decoded = [_decode_row(row) for row in rows]
    for row in decoded:
        row["review_status"] = (
            "pending"
            if row.get("review_id") is None
            else "stale"
            if row.get("item_content_hash") != row.get("content_hash")
            else "reviewed"
        )
    return decoded
