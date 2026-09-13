"""Build a public, source-traceable ADC database snapshot.

The checked-in catalog is deliberately small and reviewable.  Literature and
trial records are fetched into ignored local paths, while this command records
their source windows and hashes in a manifest.  No generative model is called.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from adc_evidence.ingestion.pipeline import run_pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_AS_OF = "2026-09-30"

LITERATURE_TOPIC_RULE_VERSION = "literature-topic-rule-v1"
LITERATURE_TOPIC_RULES: dict[str, tuple[str, ...]] = {
    "mechanism": (
        "mechanism", "internalization", "internalisation", "bystander",
        "linker", "payload", "release", "resistance", "pharmacokinetic",
        "pharmacodynamics", "preclinical",
    ),
    "efficacy": (
        "efficacy", "antitumor", "anti-tumor", "objective response",
        "response rate", "progression-free survival", "overall survival",
        "clinical activity", "tumor regression", "tumour regression", "orr", "pfs", "os",
    ),
    "safety": (
        "safety", "adverse event", "toxicity", "tolerability", "neutropenia",
        "thrombocytopenia", "interstitial lung disease", "pneumonitis", "neuropathy",
        "ocular", "keratopathy",
    ),
}


def classify_literature_text(title: str, abstract: str | None) -> dict[str, list[str]]:
    """Apply transparent lexical rules to a PubMed title and abstract."""
    text = f"{title} {abstract or ''}".casefold()

    def matches(term: str) -> bool:
        normalized = term.casefold()
        # Acronyms must be standalone tokens; substring matching would mark
        # ordinary words such as ``most`` as containing the efficacy acronym
        # ``OS``.
        if re.fullmatch(r"[a-z0-9]{2,4}", normalized):
            return re.search(rf"\b{re.escape(normalized)}\b", text) is not None
        return normalized in text

    matched = {
        topic: [term for term in terms if matches(term)]
        for topic, terms in LITERATURE_TOPIC_RULES.items()
    }
    return {topic: list(dict.fromkeys(terms)) for topic, terms in matched.items() if terms}


def classify_public_literature(database: Path) -> dict[str, object]:
    """Persist topic labels without changing the canonical document records."""
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS literature_topics (
                document_id TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                topic TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                matched_terms_json TEXT NOT NULL,
                review_status TEXT NOT NULL,
                PRIMARY KEY (document_id, topic)
            )
            """
        )
        connection.execute("DELETE FROM literature_topics")
        topic_counts = {topic: 0 for topic in LITERATURE_TOPIC_RULES}
        classified_documents = 0
        rows = connection.execute(
            "SELECT document_id, source_record_id, title, abstract FROM documents WHERE source='pubmed'"
        ).fetchall()
        for document_id, source_record_id, title, abstract in rows:
            matched = classify_literature_text(str(title), abstract)
            if matched:
                classified_documents += 1
            for topic, terms in matched.items():
                topic_counts[topic] += 1
                connection.execute(
                    """
                    INSERT INTO literature_topics
                      (document_id, source_record_id, topic, rule_version,
                       matched_terms_json, review_status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (document_id, source_record_id, topic, LITERATURE_TOPIC_RULE_VERSION,
                     json.dumps(terms, ensure_ascii=False), "needs_review"),
                )
        connection.commit()
    return {
        "rule_version": LITERATURE_TOPIC_RULE_VERSION,
        "topic_counts": topic_counts,
        "classified_document_count": classified_documents,
        "unclassified_document_count": max(0, len(rows) - classified_documents),
        "review_status": "needs_review",
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _catalog_hash(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(content).hexdigest()


def _catalog_summary(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Public ADC catalog must not be empty")
    ids = [str(row.get("adc_id", "")).strip() for row in rows]
    if any(not item for item in ids) or len(ids) != len(set(ids)):
        raise ValueError("Public ADC catalog needs unique nonempty adc_id values")
    names = [str(row.get("adc_name", "")).strip() for row in rows]
    if any(not item for item in names) or len(names) != len(set(names)):
        raise ValueError("Public ADC catalog needs unique nonempty adc_name values")
    statuses = {}
    for row in rows:
        status = str(row.get("catalog_status", "")).strip()
        if status not in {"marketed", "withdrawn", "approved_not_marketed"}:
            raise ValueError(f"Unsupported catalog_status for {row.get('adc_id')}")
        statuses[status] = statuses.get(status, 0) + 1
    return {
        "row_count": len(rows),
        "catalog_sha256": f"sha256:{_catalog_hash(path)}",
        "status_counts": dict(sorted(statuses.items())),
        "adc_ids": ids,
    }


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("--as-of must use YYYY-MM-DD") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--as-of", default=DEFAULT_AS_OF)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--raw-root", type=Path)
    parser.add_argument("--quality-report", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--pubmed-max", type=int, default=1000)
    parser.add_argument("--trial-page-size", type=int, default=100)
    parser.add_argument("--trial-max-pages", type=int, default=20)
    parser.add_argument("--source-retries", type=int, default=3)
    parser.add_argument("--source-retry-delay", type=float, default=1.0)
    parser.add_argument(
        "--include-adcdb",
        action="store_true",
        help="Also query the undocumented ADCdb web pages; off by default.",
    )
    parser.add_argument("--strict", action="store_true")
    return parser


def build_public_dataset(args: argparse.Namespace) -> dict[str, object]:
    catalog = args.catalog.resolve()
    if not catalog.is_file():
        raise FileNotFoundError(catalog)
    catalog_info = _catalog_summary(catalog)
    as_of = _parse_date(str(args.as_of))
    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    database = (args.database or PROJECT_ROOT / "data" / "processed" / f"adc_public_{as_of.isoformat()}.db").resolve()
    raw_root = (args.raw_root or PROJECT_ROOT / "data" / "raw" / f"public_{as_of.isoformat()}").resolve()
    quality_report = (args.quality_report or PROJECT_ROOT / "data" / "processed" / f"adc_public_quality_{as_of.isoformat()}.json").resolve()
    manifest_path = (args.manifest or PROJECT_ROOT / "data" / "processed" / f"adc_public_manifest_{as_of.isoformat()}.json").resolve()
    pipeline_args = argparse.Namespace(
        database=database,
        seed=catalog,
        raw_root=raw_root,
        quality_report=quality_report,
        pubmed_max=args.pubmed_max,
        trial_page_size=args.trial_page_size,
        trial_max_pages=args.trial_max_pages,
        adcdb_limit=catalog_info["row_count"],
        skip_pubmed=False,
        skip_trials=False,
        skip_adcdb=not args.include_adcdb,
        strict=args.strict,
        source_retries=args.source_retries,
        source_retry_delay=args.source_retry_delay,
    )
    summary = run_pipeline(pipeline_args)
    literature_topics = classify_public_literature(database)
    manifest = {
        "schema_version": "public-adc-dataset-v1",
        "dataset_id": f"adc-public-{as_of.isoformat()}",
        "requested_as_of": as_of.isoformat(),
        "observed_at": observed_at,
        "source_data_available_through": min(as_of, date.fromisoformat(observed_at[:10])).isoformat(),
        "as_of_status": "future_target_pending" if as_of > date.fromisoformat(observed_at[:10]) else "observed_window",
        "catalog": catalog_info,
        "catalog_path": str(catalog),
        "database_path": str(database),
        "database_sha256": f"sha256:{_sha256(database)}" if database.exists() else None,
        "raw_root": str(raw_root),
        "quality_report_path": str(quality_report),
        "pipeline_summary": summary,
        "literature_topic_summary": literature_topics,
        "redistribution_status": "candidate_pending_primary_source_and_license_review",
        "model_api_used": False,
        "notes": [
            "The target window may be later than the build date; no future records are inferred.",
            "The catalog contains structured candidates; primary regulator checks remain required.",
            "Literature topics are lexical rule labels for mechanism, efficacy, and safety triage; they are not human relevance judgments.",
            "Raw responses and generated SQLite files are local ignored artifacts.",
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    args = build_parser().parse_args()
    manifest = build_public_dataset(args)
    summary = manifest["pipeline_summary"]
    print(f"Public dataset {manifest['dataset_id']}: {summary['status']}")
    print(f"ADC catalog: {manifest['catalog']['row_count']}")
    print(f"Clinical trials: {summary['trial_records']}")
    print(f"PubMed documents: {summary['pubmed_documents']}")
    print(f"Manifest: {manifest['database_path']}")


if __name__ == "__main__":
    main()
