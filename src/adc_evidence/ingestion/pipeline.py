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
from adc_evidence.facts import (
    adc_seed_fact_sets,
    adcdb_fact_sets,
    publication_fact_sets,
    record_fact_sets,
    stable_snapshot_id,
    trial_fact_sets,
)
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
from adc_evidence.refresh_ops import retry_call
from adc_evidence.repository import (
    data_quality_metrics,
    finish_ingestion_run,
    finish_source_run,
    source_run_statuses,
    start_ingestion_run,
    start_source_run,
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
    parser.add_argument(
        "--seed",
        type=Path,
        default=DEFAULT_SEED_PATH,
        help="CSV seed/catalog used to define the ADC scope for this run.",
    )
    parser.add_argument("--raw-root", type=Path, default=RAW_DATA_PATH)
    parser.add_argument("--quality-report", type=Path, default=QUALITY_REPORT_PATH)
    parser.add_argument("--pubmed-max", type=int, default=200)
    parser.add_argument("--trial-page-size", type=int, default=100)
    parser.add_argument("--trial-max-pages", type=int, default=20)
    parser.add_argument("--adcdb-limit", type=int, default=10)
    parser.add_argument("--skip-pubmed", action="store_true")
    parser.add_argument("--skip-trials", action="store_true")
    parser.add_argument("--skip-adcdb", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--source-retries", type=int, default=3)
    parser.add_argument("--source-retry-delay", type=float, default=1.0)
    return parser


def run_pipeline(args: argparse.Namespace) -> dict[str, object]:
    run_id = getattr(args, "run_id", None) or _run_id()
    started_at = utc_now()
    run_directory = args.raw_root / run_id
    seed_path = Path(getattr(args, "seed", DEFAULT_SEED_PATH))
    seed_records = load_seed_records(seed_path)
    seed_by_id = {record.adc_id: record for record in seed_records}
    normalizer = EntityNormalizer(seed_path=seed_path)
    adc_names = [record.adc_name for record in seed_records]
    # Include canonical names and catalog aliases in PubMed queries. Aliases
    # such as RM-1929/Akalux are often used without the generic "ADC" phrase.
    adc_search_names = list(dict.fromkeys(
        alias
        for record in seed_records
        for alias in (record.adc_name, *record.aliases)
        if alias
    ))
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

    initialize_database(args.database, seed_path)
    upsert_entity_aliases(args.database, _alias_rows(normalizer))
    start_ingestion_run(args.database, run_id, started_at, parameters)
    summary["seed_fact_sync"] = record_fact_sets(
        args.database,
        [
            fact_set
            for seed_record in seed_records
            for fact_set in adc_seed_fact_sets(
                seed_record,
                observed_at=started_at,
            )
        ],
    )

    source_retries = int(getattr(args, "source_retries", 3))
    source_retry_delay = float(getattr(args, "source_retry_delay", 1.0))

    if not args.skip_adcdb:
        source_started_at = utc_now()
        start_source_run(args.database, run_id, "adcdb", source_started_at)
        attempts = 0
        try:
            (
                (adcdb_records, source_records, adcdb_errors),
                attempts,
            ) = retry_call(
                lambda: collect_adcdb(
                    adc_names[: args.adcdb_limit], run_directory / "adcdb"
                ),
                max_attempts=source_retries,
                base_delay_seconds=source_retry_delay,
            )
            adcdb_run_errors = list(adcdb_errors)
            errors.extend(f"adcdb: {message}" for message in adcdb_errors)
            upsert_source_records(
                args.database,
                source_records,
                ingestion_run_id=run_id,
                parser_version="adcdb_html_v1",
            )
            source_by_id = {
                source_record.source_record_id: source_record
                for source_record in source_records
            }
            adcdb_fact_observations = []
            for adcdb_record in adcdb_records:
                canonical = normalizer.canonical_adc(adcdb_record.adc_name)
                if not canonical:
                    message = (
                        f"unmatched ADC name {adcdb_record.adc_name} "
                        f"({adcdb_record.adcdb_id})"
                    )
                    adcdb_run_errors.append(message)
                    errors.append(f"adcdb: {message}")
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
                source_record = source_by_id[adcdb_record.adcdb_id]
                adcdb_fact_observations.extend(
                    adcdb_fact_sets(
                        adcdb_record,
                        adc_id,
                        observed_at=source_record.retrieved_at,
                        snapshot_id=stable_snapshot_id(
                            source_record.source,
                            source_record.source_record_id,
                            source_record.sha256,
                        ),
                        normalizer=normalizer,
                    )
                )
            summary["adcdb_fact_sync"] = record_fact_sets(
                args.database,
                adcdb_fact_observations,
            )
            summary["adcdb_records"] = len(adcdb_records)
            source_status = "partial" if adcdb_run_errors else "complete"
            summary["adcdb_source_run"] = finish_source_run(
                args.database,
                run_id,
                "adcdb",
                utc_now(),
                status=source_status,
                attempts=attempts,
                expected_count=min(args.adcdb_limit, len(adc_names)),
                record_ids=[record.adcdb_id for record in adcdb_records],
                is_complete=not adcdb_run_errors,
                error_text="\n".join(adcdb_run_errors) if adcdb_run_errors else None,
                details={"requested_adc_names": adc_names[: args.adcdb_limit]},
            )
        except Exception as error:
            errors.append(f"adcdb collector failed: {error}")
            summary["adcdb_source_run"] = finish_source_run(
                args.database,
                run_id,
                "adcdb",
                utc_now(),
                status="failed",
                attempts=attempts or source_retries,
                expected_count=min(args.adcdb_limit, len(adc_names)),
                is_complete=False,
                error_text=str(error),
            )
    else:
        start_source_run(args.database, run_id, "adcdb", started_at)
        summary["adcdb_source_run"] = finish_source_run(
            args.database,
            run_id,
            "adcdb",
            utc_now(),
            status="skipped",
            attempts=0,
            expected_count=None,
            is_complete=False,
        )

    if not args.skip_trials:
        source_started_at = utc_now()
        start_source_run(args.database, run_id, "clinicaltrials", source_started_at)
        attempts = 0
        try:
            (
                (trials, source_records, dataset_version, collection_info),
                attempts,
            ) = retry_call(
                lambda: collect_clinical_trials(
                    adc_search_names,
                    run_directory / "clinicaltrials",
                    page_size=args.trial_page_size,
                    max_pages=args.trial_max_pages,
                ),
                max_attempts=source_retries,
                base_delay_seconds=source_retry_delay,
            )
            upsert_source_records(
                args.database,
                source_records,
                ingestion_run_id=run_id,
                parser_version="clinicaltrials_api_v2",
            )
            upsert_trials(args.database, trials)
            trial_sources = {
                source_record.source_record_id: source_record
                for source_record in source_records
            }
            summary["trial_fact_sync"] = record_fact_sets(
                args.database,
                [
                    fact_set
                    for trial in trials
                    for fact_set in trial_fact_sets(
                        trial,
                        observed_at=trial_sources[trial.nct_id].retrieved_at,
                        snapshot_id=stable_snapshot_id(
                            "clinicaltrials",
                            trial.nct_id,
                            trial.checksum,
                        ),
                    )
                ],
            )
            links, evidence = trial_links_and_evidence(trials, normalizer)
            upsert_entity_links(args.database, links)
            upsert_evidence(args.database, evidence)
            summary["trial_records"] = len(trials)
            summary["clinicaltrials_dataset_version"] = dataset_version
            summary["clinicaltrials_collection"] = collection_info
            trial_complete = not bool(collection_info.get("truncated"))
            total_count = collection_info.get("total_count")
            if total_count is not None:
                trial_complete = trial_complete and int(total_count) == len(trials)
            source_status = "complete" if trial_complete else "partial"
            if not trial_complete:
                errors.append("clinicaltrials: collection was truncated or incomplete")
            summary["clinicaltrials_source_run"] = finish_source_run(
                args.database,
                run_id,
                "clinicaltrials",
                utc_now(),
                status=source_status,
                attempts=attempts,
                expected_count=int(total_count) if total_count is not None else None,
                record_ids=[trial.nct_id for trial in trials],
                is_complete=trial_complete,
                error_text=None if trial_complete else "collection truncated or incomplete",
                details={
                    "dataset_version": dataset_version,
                    **collection_info,
                },
            )
        except Exception as error:
            errors.append(f"clinicaltrials collector failed: {error}")
            summary["clinicaltrials_source_run"] = finish_source_run(
                args.database,
                run_id,
                "clinicaltrials",
                utc_now(),
                status="failed",
                attempts=attempts or source_retries,
                expected_count=None,
                is_complete=False,
                error_text=str(error),
            )
    else:
        start_source_run(args.database, run_id, "clinicaltrials", started_at)
        summary["clinicaltrials_source_run"] = finish_source_run(
            args.database,
            run_id,
            "clinicaltrials",
            utc_now(),
            status="skipped",
            attempts=0,
            expected_count=None,
            is_complete=False,
        )

    if not args.skip_pubmed:
        source_started_at = utc_now()
        start_source_run(args.database, run_id, "pubmed", source_started_at)
        attempts = 0
        try:
            (
                (documents, source_records, query, total_count),
                attempts,
            ) = retry_call(
                lambda: collect_pubmed(
                    adc_search_names,
                    run_directory / "pubmed",
                    max_records=args.pubmed_max,
                    coverage_names=adc_names,
                ),
                max_attempts=source_retries,
                base_delay_seconds=source_retry_delay,
            )
            upsert_source_records(
                args.database,
                source_records,
                ingestion_run_id=run_id,
                parser_version="pubmed_xml_v1",
            )
            upsert_documents(args.database, documents)
            document_sources = {
                source_record.source_record_id: source_record
                for source_record in source_records
            }
            summary["publication_fact_sync"] = record_fact_sets(
                args.database,
                [
                    fact_set
                    for document in documents
                    for fact_set in publication_fact_sets(
                        document,
                        observed_at=document_sources[
                            document.source_record_id
                        ].retrieved_at,
                        snapshot_id=stable_snapshot_id(
                            "pubmed",
                            document.source_record_id,
                            document.checksum,
                        ),
                    )
                ],
            )
            links, evidence = document_links_and_evidence(documents, normalizer)
            upsert_entity_links(args.database, links)
            upsert_evidence(args.database, evidence)
            summary["pubmed_documents"] = len(documents)
            summary["pubmed_query"] = query
            summary["pubmed_query_transport"] = (
                "POST" if len(query.encode("utf-8")) > 1800 else "GET"
            )
            summary["pubmed_total_matches"] = total_count
            summary["pubmed_truncated"] = total_count > len(documents)
            pubmed_complete = total_count == len(documents)
            expected_capture = min(total_count, args.pubmed_max)
            capture_succeeded = len(documents) == expected_capture
            source_status = "complete" if capture_succeeded else "partial"
            if not capture_succeeded:
                errors.append(
                    f"pubmed: collected {len(documents)} of {expected_capture} requested records"
                )
            summary["pubmed_source_run"] = finish_source_run(
                args.database,
                run_id,
                "pubmed",
                utc_now(),
                status=source_status,
                attempts=attempts,
                expected_count=total_count,
                record_ids=[document.source_record_id for document in documents],
                is_complete=pubmed_complete,
                error_text=(
                    None
                    if capture_succeeded
                    else f"expected {expected_capture} records"
                ),
                details={
                    "query": query,
                    "max_records": args.pubmed_max,
                    "expected_capture": expected_capture,
                    "planned_truncation": total_count > args.pubmed_max,
                },
            )
        except Exception as error:
            errors.append(f"pubmed collector failed: {error}")
            summary["pubmed_source_run"] = finish_source_run(
                args.database,
                run_id,
                "pubmed",
                utc_now(),
                status="failed",
                attempts=attempts or source_retries,
                expected_count=None,
                is_complete=False,
                error_text=str(error),
            )
    else:
        start_source_run(args.database, run_id, "pubmed", started_at)
        summary["pubmed_source_run"] = finish_source_run(
            args.database,
            run_id,
            "pubmed",
            utc_now(),
            status="skipped",
            attempts=0,
            expected_count=None,
            is_complete=False,
        )

    finished_at = utc_now()
    metrics = data_quality_metrics(args.database)
    summary.update(
        {
            "finished_at": finished_at,
            "status": "complete" if not errors else "partial",
            "errors": errors,
            "quality_metrics": metrics,
            "source_runs": source_run_statuses(args.database, run_id),
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
