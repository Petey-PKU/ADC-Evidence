"""Audit a local public ADC snapshot without exposing record content or paths."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "processed" / "adc_public_2026-09-30.db"
GENERIC_SOURCE_URLS = {
    "https://www.nmpa.gov.cn",
    "https://www.fda.gov/drugs/resources-information-approved-drugs",
}
DEFAULT_AS_OF = dt.date(2026, 9, 30)
_MONTHS = {name: index for index, name in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
)}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _column_exists(connection: sqlite3.Connection, table: str, column: str) -> bool:
    return any(str(row[1]) == column for row in connection.execute(f"PRAGMA table_info({table})"))


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _is_generic_source_url(value: str) -> bool:
    normalized = value.strip().rstrip("/")
    if not normalized:
        return False
    if normalized in GENERIC_SOURCE_URLS:
        return True
    parsed = urlparse(normalized)
    return bool(parsed.netloc) and parsed.path in {"", "/"}


def _parse_source_date(value: object) -> dt.date | None:
    """Parse the date formats used by ClinicalTrials.gov and PubMed exports."""
    text = str(value or "").strip()
    if not text:
        return None
    for pattern, formatter in (
        (r"^(\d{4})-(\d{2})-(\d{2})$", lambda m: dt.date(int(m[1]), int(m[2]), int(m[3]))),
        (r"^(\d{4})-(\d{2})$", lambda m: dt.date(int(m[1]), int(m[2]), 1)),
        (r"^(\d{4})-([A-Za-z]{3})-(\d{2})$", lambda m: dt.date(int(m[1]), _MONTHS[m[2].title()], int(m[3]))),
        (r"^(\d{4})-([A-Za-z]{3})$", lambda m: dt.date(int(m[1]), _MONTHS[m[2].title()], 1)),
        (r"^(\d{4})$", lambda m: dt.date(int(m[1]), 1, 1)),
        # PubMed can emit a combined issue month such as "2022 Nov-Dec 01".
        (r"^(\d{4}) ([A-Za-z]{3})-[A-Za-z]{3} (\d{2})$", lambda m: dt.date(int(m[1]), _MONTHS[m[2].title()], int(m[3]))),
    ):
        match = re.match(pattern, text)
        if match:
            try:
                return formatter(match)
            except (KeyError, ValueError):
                return None
    return None


def _date_quality(connection: sqlite3.Connection, table: str, column: str, as_of: dt.date) -> dict[str, object]:
    if not _column_exists(connection, table, column):
        return {"status": "unknown", "reason": "column_missing", "as_of": as_of.isoformat()}
    values = [str(row[0] or "").strip() for row in connection.execute(
        f"SELECT {column} FROM {table}"
    )]
    nonempty = [value for value in values if value]
    parsed = [(value, _parse_source_date(value)) for value in nonempty]
    valid_dates = [date for _, date in parsed if date is not None]
    invalid_values = [value for value, date in parsed if date is None]
    future_values = [value for value, date in parsed if date is not None and date > as_of]
    return {
        "status": "needs_review" if invalid_values or future_values else "pass",
        "observed_count": len(values),
        "missing_count": len(values) - len(nonempty),
        "invalid_format_count": len(invalid_values),
        "invalid_examples": invalid_values[:5],
        "min_date": min(valid_dates).isoformat() if valid_dates else None,
        "max_date": max(valid_dates).isoformat() if valid_dates else None,
        "after_as_of_count": len(future_values),
        "after_as_of_examples": future_values[:5],
        "as_of": as_of.isoformat(),
    }


def _source_url_quality(connection: sqlite3.Connection, table: str) -> dict[str, object]:
    if not _column_exists(connection, table, "source_url"):
        return {"status": "unknown", "reason": "column_missing"}
    values = [str(row[0] or "").strip() for row in connection.execute(
        f"SELECT source_url FROM {table}"
    )]
    return {
        "status": "needs_review" if any(
            (not value) or (not value.startswith("https://")) for value in values
        ) else "pass",
        "record_count": len(values),
        "missing_url_count": sum(not value for value in values),
        "non_https_url_count": sum(bool(value) and not value.startswith("https://") for value in values),
        "distinct_url_count": len({value for value in values if value}),
    }


def _source_coverage(run: dict[str, object]) -> dict[str, object]:
    """Summarize a source run without treating missing denominators as zero."""
    run_status = str(run.get("status", "")).strip().lower()
    expected: int | None
    collected: int | None
    try:
        expected = int(run["expected_count"]) if run.get("expected_count") is not None else None
    except (TypeError, ValueError):
        expected = None
    try:
        collected = int(run["collected_count"]) if run.get("collected_count") is not None else None
    except (TypeError, ValueError):
        collected = None

    if run_status in {"unknown", "skipped", "failed"}:
        state = "unknown"
    elif run_status == "complete" and bool(run.get("is_complete")) and expected is not None:
        state = "complete" if collected is None or collected >= expected else "partial"
    elif run_status == "partial" or not bool(run.get("is_complete")):
        state = "partial"
    else:
        state = "unknown"

    ratio = None
    ratio_reason = None
    if expected is None or expected <= 0:
        ratio_reason = "expected_count_missing_or_nonpositive"
    elif collected is None:
        ratio_reason = "collected_count_missing"
    else:
        ratio = round(collected / expected, 6)
    return {
        "run_status": run_status or "unknown",
        "coverage_state": state,
        "expected_count": expected,
        "collected_count": collected,
        "coverage_ratio": ratio,
        "coverage_ratio_reason": ratio_reason,
    }


def _late_publication_dates(
    connection: sqlite3.Connection, *, as_of: dt.date, raw_root: Path | None
) -> dict[str, object]:
    """Inspect late issue dates without changing records or declaring eligibility.

    Raw files are read only inside an explicitly allowed directory, and only
    after binding the bytes to the document checksum and its unique PMID.
    NLM processing dates are kept separate from electronic publication dates.
    """
    required = ("source", "source_record_id", "publication_date", "raw_path", "checksum")
    if any(not _column_exists(connection, "documents", column) for column in required):
        return {"status": "unknown", "reason": "provenance_columns_missing"}
    allowed_root = raw_root.resolve() if raw_root is not None else None
    records = []
    for row in connection.execute(
        "SELECT source_record_id, publication_date, raw_path, checksum "
        "FROM documents WHERE source='pubmed' ORDER BY source_record_id"
    ):
        issue_date = _parse_source_date(row["publication_date"])
        if issue_date is None or issue_date <= as_of:
            continue
        record = {
            "pmid": row["source_record_id"],
            "issue_date": row["publication_date"],
            "raw_sha256": None,
            "status": "unknown",
            "reason": "raw_root_not_supplied",
        }
        records.append(record)
        if allowed_root is None:
            continue
        raw_path = Path(row["raw_path"] or "")
        # Relative paths cannot be safely resolved from an arbitrary CLI cwd.
        if not raw_path.is_absolute() or not raw_path.resolve().is_relative_to(allowed_root):
            record["reason"] = "raw_path_outside_allowed_root"
            continue
        try:
            raw = raw_path.read_bytes()
        except OSError:
            record["reason"] = "raw_file_unavailable"
            continue
        digest = hashlib.sha256(raw).hexdigest()
        record["raw_sha256"] = "sha256:" + digest
        if digest != row["checksum"]:
            record["reason"] = "raw_checksum_mismatch"
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            record["reason"] = "invalid_xml"
            continue
        articles = [article for article in root.findall("PubmedArticle")
                    if article.findtext("./MedlineCitation/PMID") == row["source_record_id"]]
        if len(articles) != 1:
            record["reason"] = "pmid_not_unique_in_raw"
            continue
        article = articles[0]
        dates = []
        invalid_count = 0
        for node in (article.findall("./MedlineCitation/Article/ArticleDate")
                     + article.findall("./PubmedData/History/PubMedPubDate")):
            kind = ("article:" + node.get("DateType", "unknown") if node.tag == "ArticleDate"
                    else "history:" + node.get("PubStatus", "unknown"))
            try:
                value = dt.date(*(int(node.findtext(part, "")) for part in ("Year", "Month", "Day")))
            except ValueError:
                invalid_count += 1
                continue
            dates.append({"kind": kind, "date": value.isoformat(), "on_or_before_as_of": value <= as_of})
        electronic = [d for d in dates if d["kind"] in {"article:Electronic", "history:epublish"}]
        processing = [d for d in dates if d["kind"] in {"history:pubmed", "history:entrez"}]
        accepted = [d for d in dates if d["kind"] == "history:accepted"]
        flags = []
        if invalid_count:
            flags.append("invalid_date_components")
        if any(a["date"] > p["date"] for a in accepted for p in electronic + processing):
            flags.append("acceptance_after_publication_or_indexing")
        before_electronic = any(d["on_or_before_as_of"] for d in electronic)
        before_processing = any(d["on_or_before_as_of"] for d in processing)
        record.update({
            "status": "candidate_pending_review",
            "reason": ("electronic_publication_before_cutoff" if before_electronic else
                       "indexing_before_cutoff_only" if before_processing else
                       "no_pre_cutoff_publication_or_indexing_evidence"),
            "dates": sorted(dates, key=lambda d: (d["kind"], d["date"])),
            "invalid_date_count": invalid_count,
            "chronology_flags": flags,
        })
    return {
        "status": "pending_review" if records else "no_late_issue_dates",
        "as_of": as_of.isoformat(),
        "late_issue_count": len(records),
        "reason_counts": dict(sorted(Counter(row["reason"] for row in records).items())),
        "records": records,
        "method_note": "Issue dates, electronic publication dates and NLM processing dates are distinct. "
                       "This audit does not reconstruct an as-of database or establish independent human review; "
                       "retrieval and source revision times still require a frozen snapshot protocol.",
    }


def audit_database(
    database: Path, *, as_of: dt.date = DEFAULT_AS_OF, raw_root: Path | None = None
) -> dict[str, object]:
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
        record_date_quality = {
            "documents.publication_date": _date_quality(connection, "documents", "publication_date", as_of),
            "trials.last_update_date": _date_quality(connection, "trials", "last_update_date", as_of),
        }
        late_publication_dates = _late_publication_dates(connection, as_of=as_of, raw_root=raw_root)
        source_url_quality = {
            "documents": _source_url_quality(connection, "documents"),
            "trials": _source_url_quality(connection, "trials"),
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
        link_coverage_by_adc = {
            str(row["adc_id"]): {
                "trial_record_count": int(row["trial_record_count"]),
                "document_record_count": int(row["document_record_count"]),
            }
            for row in connection.execute(
                """
                SELECT a.adc_id,
                       COUNT(DISTINCT CASE WHEN l.source_record_type='trial' THEN l.source_record_id END) AS trial_record_count,
                       COUNT(DISTINCT CASE WHEN l.source_record_type='document' THEN l.source_record_id END) AS document_record_count
                FROM adcs AS a
                LEFT JOIN entity_links AS l
                  ON l.entity_type='adc' AND l.entity_id=a.adc_id
                GROUP BY a.adc_id ORDER BY a.adc_id
                """
            )
        }
        orphan_link_counts = {
            "trial": int(connection.execute(
                """
                SELECT COUNT(*) FROM entity_links AS l
                LEFT JOIN trials AS t ON t.nct_id=l.source_record_id
                WHERE l.source_record_type='trial' AND t.nct_id IS NULL
                """
            ).fetchone()[0]),
            "document": int(connection.execute(
                """
                SELECT COUNT(*) FROM entity_links AS l
                LEFT JOIN documents AS d ON d.document_id=l.source_record_id
                WHERE l.source_record_type='document' AND d.document_id IS NULL
                """
            ).fetchone()[0]),
        }
        match_method_counts = {
            f"{row['source_record_type']}:{row['match_method']}": int(row["count"])
            for row in connection.execute(
                """
                SELECT source_record_type, match_method, COUNT(*) AS count
                FROM entity_links
                GROUP BY source_record_type, match_method
                ORDER BY source_record_type, match_method
                """
            )
        }
        duplicate_link_groups = [
            int(row["link_count"])
            for row in connection.execute(
                """
                SELECT COUNT(*) AS link_count
                FROM entity_links
                GROUP BY entity_type, entity_id, source_record_type, source_record_id
                HAVING COUNT(*) > 1
                """
            )
        ]
        entity_link_integrity: dict[str, object] = {
            "unknown_adc_entity_count": int(connection.execute(
                """
                SELECT COUNT(*) FROM entity_links AS l
                LEFT JOIN adcs AS a ON a.adc_id=l.entity_id
                WHERE l.entity_type='adc' AND a.adc_id IS NULL
                """
            ).fetchone()[0]),
            "duplicate_logical_link_group_count": len(duplicate_link_groups),
            "duplicate_logical_link_extra_row_count": sum(count - 1 for count in duplicate_link_groups),
            "max_links_per_logical_record": max(duplicate_link_groups, default=1),
        }
        if _table_exists(connection, "entity_aliases"):
            entity_link_integrity["unmatched_alias_count"] = int(connection.execute(
                """
                SELECT COUNT(*) FROM entity_links AS l
                LEFT JOIN entity_aliases AS a
                  ON a.entity_type=l.entity_type
                 AND a.entity_id=l.entity_id
                 AND a.normalized_alias=l.matched_alias
                WHERE a.entity_id IS NULL
                """
            ).fetchone()[0])
            entity_link_integrity["alias_validation_status"] = (
                "pass" if entity_link_integrity["unmatched_alias_count"] == 0 else "needs_review"
            )
        else:
            entity_link_integrity["unmatched_alias_count"] = None
            entity_link_integrity["alias_validation_status"] = "unknown"

        fact_coverage: dict[str, int] = {}
        fact_provenance: dict[str, dict[str, object]] = {}
        fact_source_quality: dict[str, dict[str, int]] = {}
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
            if _table_exists(connection, "fact_evidence"):
                for row in connection.execute(
                    """
                    SELECT f.predicate,
                           COUNT(DISTINCT f.fact_id) AS fact_count,
                           COUNT(DISTINCT CASE WHEN e.fact_id IS NOT NULL THEN f.fact_id END) AS evidence_count,
                           COUNT(DISTINCT CASE WHEN TRIM(COALESCE(e.source_url, '')) <> '' THEN f.fact_id END) AS url_count,
                           COUNT(DISTINCT CASE WHEN TRIM(COALESCE(e.source_url, '')) <> '' THEN e.source_url END) AS distinct_url_count,
                           GROUP_CONCAT(DISTINCT e.source) AS source_types
                    FROM facts AS f
                    LEFT JOIN fact_evidence AS e
                      ON e.fact_id=f.fact_id AND e.is_current=1 AND e.valid_to IS NULL
                    WHERE f.subject_type='adc' AND f.valid_to IS NULL
                    GROUP BY f.predicate ORDER BY f.predicate
                    """
                ):
                    source_types = sorted(
                        value.strip() for value in str(row["source_types"] or "").split(",") if value.strip()
                    )
                    fact_provenance[str(row["predicate"])] = {
                        "fact_count": int(row["fact_count"]),
                        "with_current_evidence_count": int(row["evidence_count"]),
                        "with_source_url_count": int(row["url_count"]),
                        "distinct_source_url_count": int(row["distinct_url_count"]),
                        "source_types": source_types,
                    }
                url_rows = connection.execute(
                    """
                    SELECT f.predicate, e.source_url
                    FROM facts AS f
                    LEFT JOIN fact_evidence AS e
                      ON e.fact_id=f.fact_id AND e.is_current=1 AND e.valid_to IS NULL
                    WHERE f.subject_type='adc' AND f.valid_to IS NULL
                    """
                ).fetchall()
                quality: dict[str, dict[str, int]] = {}
                for url_row in url_rows:
                    predicate = str(url_row["predicate"])
                    value = str(url_row["source_url"] or "").strip()
                    url_counts = quality.setdefault(
                        predicate,
                        {"missing_url_count": 0, "generic_url_count": 0},
                    )
                    if not value:
                        url_counts["missing_url_count"] += 1
                    elif _is_generic_source_url(value):
                        url_counts["generic_url_count"] += 1
                fact_source_quality = dict(sorted(quality.items()))

        source_runs: list[dict[str, object]] = []
        latest_source_runs: dict[str, dict[str, object]] = {}
        if _table_exists(connection, "ingestion_source_runs"):
            run_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(ingestion_source_runs)")
            }
            # Older local snapshots do not have timestamps. Keep auditing them,
            # while using the latest finished/started run when the metadata is
            # available in current snapshots.
            has_timestamps = "started_at" in run_columns or "finished_at" in run_columns
            selected_columns = ["source", "status", "expected_count", "collected_count", "is_complete", "details_json"]
            if "run_id" in run_columns:
                selected_columns.insert(0, "run_id")
            if "started_at" in run_columns:
                selected_columns.append("started_at")
            if "finished_at" in run_columns:
                selected_columns.append("finished_at")
            query = "SELECT " + ", ".join(selected_columns) + " FROM ingestion_source_runs"
            if has_timestamps:
                query += " ORDER BY COALESCE(finished_at, started_at), rowid"
            else:
                query += " ORDER BY rowid"
            for row in connection.execute(query):
                values = {
                    column: row[column] if isinstance(row, sqlite3.Row) else row[index]
                    for index, column in enumerate(selected_columns)
                }
                details: dict[str, object] = {}
                try:
                    parsed = json.loads(str(values.get("details_json") or "{}"))
                    if isinstance(parsed, dict):
                        for key in ("total_count", "expected_capture", "planned_truncation", "truncated"):
                            if key in parsed:
                                details[key] = parsed[key]
                except (TypeError, ValueError, json.JSONDecodeError):
                    details = {"details_parse_error": True}
                run = {
                    "source": str(values["source"]),
                    "status": str(values["status"]),
                    "expected_count": values["expected_count"],
                    "collected_count": values["collected_count"],
                    "is_complete": bool(values["is_complete"]),
                    **details,
                }
                for field in ("run_id", "started_at", "finished_at"):
                    if field in values and values[field] is not None:
                        run[field] = str(values[field])
                source_runs.append(run)
                latest_source_runs[run["source"]] = run

    run_summary = latest_source_runs.values() if latest_source_runs else source_runs
    incomplete_sources = sorted({
        str(row["source"])
        for row in run_summary
        if row["status"] != "complete" or not row["is_complete"]
    })
    source_coverage = {
        str(row["source"]): _source_coverage(row)
        for row in run_summary
    }
    partial_sources = sorted(
        source for source, summary in source_coverage.items()
        if summary["coverage_state"] == "partial"
    )
    unknown_sources = sorted(
        source for source, summary in source_coverage.items()
        if summary["coverage_state"] == "unknown"
    )
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
        "link_coverage_by_adc": link_coverage_by_adc,
        "zero_link_adc_ids": sorted(
            adc_id for adc_id, values in link_coverage_by_adc.items()
            if not values["trial_record_count"] and not values["document_record_count"]
        ),
        "missing_trial_link_adc_ids": sorted(
            adc_id for adc_id, values in link_coverage_by_adc.items()
            if not values["trial_record_count"]
        ),
        "missing_document_link_adc_ids": sorted(
            adc_id for adc_id, values in link_coverage_by_adc.items()
            if not values["document_record_count"]
        ),
        "orphan_link_counts": orphan_link_counts,
        "entity_link_integrity": entity_link_integrity,
        "match_method_counts": match_method_counts,
        "record_date_quality": record_date_quality,
        "late_publication_date_review": late_publication_dates,
        "source_url_quality": source_url_quality,
        "adc_fact_coverage": fact_coverage,
        "adc_fact_provenance": fact_provenance,
        "adc_fact_source_quality": fact_source_quality,
        "adc_fact_source_quality_reasons": sorted({
            reason
            for reason, condition in (
                ("missing_or_generic_url", any(
                    values["missing_url_count"] > 0 or values["generic_url_count"] > 0
                    for values in fact_source_quality.values()
                )),
                ("curated_seed_not_independently_reviewed", any(
                    "curated_seed" in provenance.get("source_types", [])
                    for provenance in fact_provenance.values()
                )),
            )
            if condition
        }),
        "adc_fact_source_quality_status": (
            "pass"
            if not any((
                values["missing_url_count"] > 0
                or values["generic_url_count"] > 0
                for values in fact_source_quality.values()
            ))
            and not any(
                "curated_seed" in provenance.get("source_types", [])
                for provenance in fact_provenance.values()
            )
            else "needs_review"
        ),
        "source_runs": source_runs,
        "source_run_history_count": len(source_runs),
        "latest_source_runs": {
            source: latest_source_runs[source]
            for source in sorted(latest_source_runs)
        },
        "source_coverage": {
            source: source_coverage[source]
            for source in sorted(source_coverage)
        },
        "partial_sources": partial_sources,
        "unknown_sources": unknown_sources,
        "incomplete_sources": incomplete_sources,
        "status": "partial" if incomplete_sources else "complete",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=lambda value: dt.date.fromisoformat(value), default=DEFAULT_AS_OF)
    parser.add_argument("--raw-root", type=Path, help="Explicit allowed root for checksum-bound PubMed date review")
    args = parser.parse_args()
    report = audit_database(args.database, as_of=args.as_of, raw_root=args.raw_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "counts": report["counts"],
        "incomplete_sources": report["incomplete_sources"],
        "adc_fact_source_quality_status": report["adc_fact_source_quality_status"],
        "adc_fact_source_quality_reasons": report["adc_fact_source_quality_reasons"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
