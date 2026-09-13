"""Audit a local public ADC snapshot without exposing record content or paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "processed" / "adc_public_2026-09-30.db"


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def audit_database(database: Path) -> dict[str, object]:
    """Return deterministic quality and coverage statistics for a snapshot."""
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(database)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        required = ("adcs", "trials", "documents", "entity_links")
        missing = [table for table in required if not _table_exists(connection, table)]
        if missing:
            raise ValueError("Snapshot is missing required tables: " + ", ".join(missing))

        counts = {table: _count(connection, table) for table in required}
        identifier_counts = {
            "adcs": tuple(connection.execute("SELECT COUNT(*), COUNT(DISTINCT adc_id) FROM adcs").fetchone()),
            "trials": tuple(connection.execute("SELECT COUNT(*), COUNT(DISTINCT nct_id) FROM trials").fetchone()),
            "documents": tuple(connection.execute("SELECT COUNT(*), COUNT(DISTINCT document_id) FROM documents").fetchone()),
        }
        duplicate_identifier_counts = {
            table: total - distinct
            for table, (total, distinct) in identifier_counts.items()
        }

        link_stats = {
            str(row["source_record_type"]): {
                "link_count": int(row["link_count"]),
                "distinct_source_record_count": int(row["source_record_count"]),
                "distinct_entity_count": int(row["entity_count"]),
            }
            for row in connection.execute(
                """
                SELECT source_record_type,
                       COUNT(*) AS link_count,
                       COUNT(DISTINCT source_record_id) AS source_record_count,
                       COUNT(DISTINCT entity_id) AS entity_count
                FROM entity_links
                GROUP BY source_record_type
                ORDER BY source_record_type
                """
            )
        }
        linked_trial_count = int(connection.execute(
            """
            SELECT COUNT(DISTINCT l.source_record_id)
            FROM entity_links AS l JOIN trials AS t
              ON l.source_record_type='trial' AND l.source_record_id=t.nct_id
            """
        ).fetchone()[0])
        linked_document_count = int(connection.execute(
            """
            SELECT COUNT(DISTINCT l.source_record_id)
            FROM entity_links AS l JOIN documents AS d
              ON l.source_record_type='document' AND l.source_record_id=d.document_id
            """
        ).fetchone()[0])

        fact_coverage: dict[str, int] = {}
        if _table_exists(connection, "facts"):
            fact_coverage = {
                str(row["predicate"]): int(row["value_count"])
                for row in connection.execute(
                    """
                    SELECT predicate, COUNT(*) AS value_count
                    FROM facts
                    WHERE subject_type='adc' AND valid_to IS NULL
                    GROUP BY predicate ORDER BY predicate
                    """
                )
            }

        source_runs: list[dict[str, object]] = []
        if _table_exists(connection, "ingestion_source_runs"):
            for row in connection.execute(
                """
                SELECT source, status, expected_count, collected_count,
                       is_complete, details_json
                FROM ingestion_source_runs
                ORDER BY source
                """
            ):
                details: dict[str, object] = {}
                try:
                    parsed = json.loads(str(row["details_json"] or "{}"))
                    if isinstance(parsed, dict):
                        for key in ("total_count", "expected_capture", "planned_truncation", "truncated"):
                            if key in parsed:
                                details[key] = parsed[key]
                except (TypeError, ValueError, json.JSONDecodeError):
                    details = {"details_parse_error": True}
                source_runs.append({
                    "source": str(row["source"]),
                    "status": str(row["status"]),
                    "expected_count": row["expected_count"],
                    "collected_count": row["collected_count"],
                    "is_complete": bool(row["is_complete"]),
                    **details,
                })

    incomplete_sources = [
        str(row["source"])
        for row in source_runs
        if row["status"] != "complete" or not row["is_complete"]
    ]
    return {
        "schema_version": "public-adc-dataset-audit-v1",
        "database_sha256": _sha256(database),
        "counts": counts,
        "distinct_identifier_counts": {
            table: distinct for table, (_, distinct) in identifier_counts.items()
        },
        "duplicate_identifier_counts": duplicate_identifier_counts,
        "entity_link_stats": link_stats,
        "linked_record_counts": {
            "trials": linked_trial_count,
            "documents": linked_document_count,
        },
        "adc_fact_coverage": fact_coverage,
        "source_runs": source_runs,
        "incomplete_sources": incomplete_sources,
        "status": "partial" if incomplete_sources else "complete",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit_database(args.database)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "counts": report["counts"],
        "incomplete_sources": report["incomplete_sources"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
