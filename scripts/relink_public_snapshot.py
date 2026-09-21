"""Rebuild public trial/document entity links after catalog alias changes.

This is an offline operation: it reads the existing SQLite snapshot and does
not contact ClinicalTrials.gov, PubMed, ADCdb, or any model API.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from adc_evidence.processing.normalize import EntityNormalizer
from adc_evidence.processing.standardize import (
    document_links_and_evidence,
    trial_links_and_evidence,
)
from adc_evidence.records import DocumentRecord, TrialRecord
from adc_evidence.repository import upsert_entity_aliases, upsert_entity_links, upsert_evidence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "processed" / "adc_public_2026-09-30.db"
DEFAULT_SEED = ROOT / "data" / "public" / "marketed_adc_catalog.csv"


def _alias_rows(normalizer: EntityNormalizer) -> list[dict[str, str]]:
    return [
        {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "canonical_name": canonical_name,
            "alias": normalized_alias,
            "normalized_alias": normalized_alias,
            "source": "project_config",
        }
        for entity_type, aliases in normalizer.aliases.items()
        for normalized_alias, entity_id, canonical_name in aliases
    ]


def _load_records(database: Path) -> tuple[list[TrialRecord], list[DocumentRecord]]:
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        trials = [
            TrialRecord(
                nct_id=row["nct_id"],
                brief_title=row["brief_title"],
                official_title=row["official_title"],
                overall_status=row["overall_status"],
                phases=json.loads(row["phases_json"] or "[]"),
                conditions=json.loads(row["conditions_json"] or "[]"),
                interventions=json.loads(row["interventions_json"] or "[]"),
                sponsor=row["sponsor"],
                enrollment=row["enrollment"],
                start_date=row["start_date"],
                completion_date=row["completion_date"],
                last_update_date=row["last_update_date"],
                primary_outcomes=json.loads(row["primary_outcomes_json"] or "[]"),
                source_url=row["source_url"],
                raw_path=row["raw_path"],
                checksum=row["checksum"],
            )
            for row in connection.execute("SELECT * FROM trials ORDER BY nct_id")
        ]
        documents = [
            DocumentRecord(
                document_id=row["document_id"],
                source=row["source"],
                source_record_id=row["source_record_id"],
                title=row["title"],
                abstract=row["abstract"],
                authors=json.loads(row["authors_json"] or "[]"),
                journal=row["journal"],
                publication_date=row["publication_date"],
                doi=row["doi"],
                source_url=row["source_url"],
                raw_path=row["raw_path"],
                checksum=row["checksum"],
            )
            for row in connection.execute("SELECT * FROM documents ORDER BY document_id")
        ]
    return trials, documents


def relink_snapshot(database: Path, seed: Path) -> dict[str, int]:
    normalizer = EntityNormalizer(seed_path=seed)
    trials, documents = _load_records(database)
    trial_links, trial_evidence = trial_links_and_evidence(trials, normalizer)
    document_links, document_evidence = document_links_and_evidence(documents, normalizer)
    with sqlite3.connect(database) as connection, connection:
        connection.execute(
            "DELETE FROM entity_links WHERE source_record_type IN ('trial','document') "
            "AND entity_type IN ('adc','target')"
        )
        connection.execute(
            "DELETE FROM evidence WHERE source IN ('clinicaltrials','pubmed') "
            "AND subject_type IN ('adc','target')"
        )
    upsert_entity_aliases(database, _alias_rows(normalizer))
    upsert_entity_links(database, [*trial_links, *document_links])
    upsert_evidence(database, [*trial_evidence, *document_evidence])
    return {
        "trial_link_count": len(trial_links),
        "document_link_count": len(document_links),
        "trial_evidence_count": len(trial_evidence),
        "document_evidence_count": len(document_evidence),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    args = parser.parse_args()
    print(json.dumps(relink_snapshot(args.database, args.seed), ensure_ascii=False))


if __name__ == "__main__":
    main()
