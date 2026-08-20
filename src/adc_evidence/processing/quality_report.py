from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path

from adc_evidence.config import DEFAULT_DATABASE_PATH, QUALITY_REPORT_PATH
from adc_evidence.database import connect
from adc_evidence.ingestion.http import utc_now, write_json
from adc_evidence.repository import data_quality_metrics


def collection_scope(database_path: Path, metrics: dict[str, object]) -> dict[str, object]:
    clinical_total = 0
    pubmed_total = 0
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT summary_json FROM ingestion_runs WHERE summary_json IS NOT NULL"
        ).fetchall()
    for row in rows:
        summary = json.loads(row[0])
        clinical = summary.get("clinicaltrials_collection") or {}
        clinical_total = max(clinical_total, int(clinical.get("total_count") or 0))
        pubmed_total = max(pubmed_total, int(summary.get("pubmed_total_matches") or 0))

    trial_count = int(metrics["trial_count"])
    document_count = int(metrics["document_count"])
    return {
        "clinicaltrials_total_matches": clinical_total or None,
        "clinicaltrials_stored": trial_count,
        "clinicaltrials_coverage": (
            round(trial_count / clinical_total, 4) if clinical_total else None
        ),
        "pubmed_total_matches": pubmed_total or None,
        "pubmed_stored": document_count,
        "pubmed_coverage": (
            round(document_count / pubmed_total, 4) if pubmed_total else None
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the database quality report.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--output", type=Path, default=QUALITY_REPORT_PATH)
    args = parser.parse_args()
    metrics = data_quality_metrics(args.database)
    report = {
        "generated_at": utc_now(),
        "database_metrics": metrics,
        "collection_scope": collection_scope(args.database, metrics),
    }
    write_json(args.output, report)
    print(f"Quality report written to {args.output}")


if __name__ == "__main__":
    main()
