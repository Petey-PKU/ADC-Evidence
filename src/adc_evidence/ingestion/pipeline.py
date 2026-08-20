from __future__ import annotations

import argparse
import traceback
from datetime import datetime, timezone
from pathlib import Path

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED_PATH,
    QUALITY_REPORT_PATH,
    RAW_DATA_PATH,
)
from adc_evidence.database import initialize_database, load_seed_records, upsert_records
from adc_evidence.ingestion.adcdb import collect_adcdb
from adc_evidence.ingestion.clinical_trials import collect_clinical_trials
from adc_evidence.ingestion.http import utc_now, write_json
from adc_evidence.ingestion.pubmed import collect_pubmed
from adc_evidence.processing.normalize import EntityNormalizer
from adc_evidence.processing.standardize import (
    adcdb_evidence,
    adcdb_to_adc_record,
    document_links_and_evidence,
    trial_links_and_evidence,
)
from adc_evidence.repository import (
    data_quality_metrics,
    finish_ingestion_run,
    start_ingestion_run,
    upsert_documents,
    upsert_entity_aliases,
    upsert_entity_links,
    upsert_evidence,
    upsert_external_identifier,
    upsert_source_records,
    upsert_trials,
)


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _alias_rows(normalizer: EntityNormalizer) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entity_type, aliases in normalizer.aliases.items():
        for normalized_alias, entity_id, canonical_name in aliases:
            rows.append(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "canonical_name": canonical_name,
                    "alias": normalized_alias,
                    "normalized_alias": normalized_alias,
                    "source": "project_config",
                }
            )
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect and standardize ADC-Evidence public data sources."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_DATA_PATH)
    parser.add_argument("--quality-report", type=Path, default=QUALITY_REPORT_PATH)
    parser.add_argument("--pubmed-max", type=int, default=200)
    parser.add_argument("--trial-page-size", type=int, default=1000)
    parser.add_argument("--trial-max-pages", type=int, default=1)
    parser.add_argument("--adcdb-limit", type=int, default=10)
    parser.add_argument("--skip-pubmed", action="store_true")
    parser.add_argument("--skip-trials", action="store_true")
    parser.add_argument("--skip-adcdb", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser


def run_pipeline(args: argparse.Namespace) -> dict[str, object]:
    run_id = _run_id()
    started_at = utc_now()
    run_directory = args.raw_root / run_id
    seed_records = load_seed_records(DEFAULT_SEED_PATH)
    seed_by_id = {record.adc_id: record for record in seed_records}
    normalizer = EntityNormalizer()
    adc_names = [record.adc_name for record in seed_records]
    errors: list[str] = []
    summary: dict[str, object] = {
        "run_id": run_id,
        "started_at": started_at,
        "adcdb_records": 0,
        "trial_records": 0,
        "pubmed_documents": 0,
    }
    parameters = vars(args).copy()
    parameters = {key: str(value) if isinstance(value, Path) else value for key, value in parameters.items()}

    initialize_database(args.database, DEFAULT_SEED_PATH)
    upsert_entity_aliases(args.database, _alias_rows(normalizer))
    start_ingestion_run(args.database, run_id, started_at, parameters)

    if not args.skip_adcdb:
        try:
            adcdb_records, source_records, adcdb_errors = collect_adcdb(
                adc_names[: args.adcdb_limit], run_directory / "adcdb"
            )
            errors.extend(f"adcdb: {message}" for message in adcdb_errors)
            upsert_source_records(args.database, source_records)
            for adcdb_record in adcdb_records:
                canonical = normalizer.canonical_adc(adcdb_record.adc_name)
                if not canonical:
                    errors.append(
                        f"adcdb: unmatched ADC name {adcdb_record.adc_name} "
                        f"({adcdb_record.adcdb_id})"
                    )
                    continue
                adc_id, _ = canonical
                standardized = adcdb_to_adc_record(
                    adcdb_record, normalizer, seed_by_id[adc_id]
                )
                upsert_records(args.database, [standardized])
                upsert_external_identifier(
                    args.database,
                    entity_type="adc",
                    entity_id=adc_id,
                    source="adcdb",
                    external_id=adcdb_record.adcdb_id,
                    source_url=adcdb_record.detail_url,
                )
                upsert_evidence(args.database, adcdb_evidence(adcdb_record, adc_id))
            summary["adcdb_records"] = len(adcdb_records)
        except Exception as error:
            errors.append(f"adcdb collector failed: {error}")

    if not args.skip_trials:
        try:
            trials, source_records, dataset_version, collection_info = collect_clinical_trials(
                adc_names,
                run_directory / "clinicaltrials",
                page_size=args.trial_page_size,
                max_pages=args.trial_max_pages,
            )
            upsert_source_records(args.database, source_records)
            upsert_trials(args.database, trials)
            links, evidence = trial_links_and_evidence(trials, normalizer)
            upsert_entity_links(args.database, links)
            upsert_evidence(args.database, evidence)
            summary["trial_records"] = len(trials)
            summary["clinicaltrials_dataset_version"] = dataset_version
            summary["clinicaltrials_collection"] = collection_info
        except Exception as error:
            errors.append(f"clinicaltrials collector failed: {error}")

    if not args.skip_pubmed:
        try:
            documents, source_records, query, total_count = collect_pubmed(
                adc_names,
                run_directory / "pubmed",
                max_records=args.pubmed_max,
            )
            upsert_source_records(args.database, source_records)
            upsert_documents(args.database, documents)
            links, evidence = document_links_and_evidence(documents, normalizer)
            upsert_entity_links(args.database, links)
            upsert_evidence(args.database, evidence)
            summary["pubmed_documents"] = len(documents)
            summary["pubmed_query"] = query
            summary["pubmed_total_matches"] = total_count
            summary["pubmed_truncated"] = total_count > len(documents)
        except Exception as error:
            errors.append(f"pubmed collector failed: {error}")

    finished_at = utc_now()
    metrics = data_quality_metrics(args.database)
    summary.update(
        {
            "finished_at": finished_at,
            "status": "complete" if not errors else "partial",
            "errors": errors,
            "quality_metrics": metrics,
        }
    )
    write_json(run_directory / "run_summary.json", summary)
    write_json(
        args.quality_report,
        {
            "generated_at": finished_at,
            "latest_run_id": run_id,
            "latest_run_status": summary["status"],
            "latest_run_errors": errors,
            "database_metrics": metrics,
        },
    )
    finish_ingestion_run(
        args.database,
        run_id,
        finished_at,
        str(summary["status"]),
        summary,
        "\n".join(errors) if errors else None,
    )
    if args.strict and errors:
        raise RuntimeError("Pipeline completed with errors:\n" + "\n".join(errors))
    return summary


def main() -> None:
    args = build_parser().parse_args()
    try:
        summary = run_pipeline(args)
        print(f"Ingestion run {summary['run_id']}: {summary['status']}")
        print(f"ADCdb records: {summary['adcdb_records']}")
        print(f"Clinical trials: {summary['trial_records']}")
        print(f"PubMed documents: {summary['pubmed_documents']}")
        if summary["errors"]:
            print("Warnings:")
            for error in summary["errors"]:
                print(f"- {error}")
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
