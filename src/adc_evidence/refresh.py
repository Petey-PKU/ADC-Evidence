from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
from argparse import Namespace
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from adc_evidence.backup import backup_database, sha256_file
from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_EMBEDDING_MODEL,
    VECTOR_INDEX_PATH,
)
from adc_evidence.database import SCHEMA_VERSION, connect, create_database
from adc_evidence.evidence_policy import load_evidence_policy
from adc_evidence.ingestion.pipeline import run_pipeline
from adc_evidence.rag.documents import (
    build_retrieval_documents,
    chunk_documents,
    persist_retrieval_corpus_incremental,
    retrieval_corpus_version,
)
from adc_evidence.rag.vector_index import build_vector_index, load_vector_index
from adc_evidence.refresh_ops import RefreshLock, evaluate_refresh_gates


def _refresh_id() -> str:
    return datetime.now(UTC).strftime("refresh_%Y%m%dT%H%M%S%fZ")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sqlite_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source)) as source_connection:
        with closing(sqlite3.connect(destination)) as destination_connection:
            source_connection.backup(destination_connection)


def _index_hashes(index_path: Path) -> dict[str, str]:
    required = ("manifest.json", "chunk_ids.json", "embeddings.npy")
    missing = [name for name in required if not (index_path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Incomplete vector index: {', '.join(missing)}")
    return {name: sha256_file(index_path / name) for name in required}


def build_release_manifest(
    *,
    release_id: str,
    run_id: str,
    database_path: Path,
    index_path: Path,
    gate_report: dict[str, object],
    corpus_summary: dict[str, object],
) -> dict[str, object]:
    """Build a verifiable binding between database, corpus and dense index."""
    index_manifest = json.loads(
        (index_path / "manifest.json").read_text(encoding="utf-8")
    )
    with closing(connect(database_path)) as connection:
        schema_versions = [
            str(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_versions ORDER BY applied_at, version"
            ).fetchall()
        ]
    corpus_version = retrieval_corpus_version(database_path)
    if index_manifest.get("retrieval_corpus_version") != corpus_version:
        raise RuntimeError("Index manifest is not bound to the staged retrieval corpus")
    return {
        "release_id": release_id,
        "run_id": run_id,
        "status": "ready",
        "created_at": datetime.now(UTC).isoformat(),
        "schema_version": SCHEMA_VERSION,
        "schema_versions": schema_versions,
        "policy_version": load_evidence_policy().policy_version,
        "database": {
            "filename": database_path.name,
            "size_bytes": database_path.stat().st_size,
            "sha256": sha256_file(database_path),
        },
        "retrieval_corpus_version": corpus_version,
        "corpus_update": corpus_summary,
        "index": {
            "manifest": index_manifest,
            "file_sha256": _index_hashes(index_path),
        },
        "quality_gates": gate_report,
    }


def publish_staged_assets(
    *,
    staged_database: Path,
    staged_index: Path,
    live_database: Path,
    live_index: Path,
    backup_directory: Path,
    release_directory: Path,
    release_manifest: dict[str, object],
) -> dict[str, object]:
    """Promote prepared assets and restore the previous pair on any failure."""
    release_id = str(release_manifest["release_id"])
    live_database.parent.mkdir(parents=True, exist_ok=True)
    live_index.parent.mkdir(parents=True, exist_ok=True)
    release_directory.mkdir(parents=True, exist_ok=True)

    incoming_database = live_database.with_name(
        f".{live_database.name}.{release_id}.incoming"
    )
    incoming_index = live_index.with_name(f".{live_index.name}.{release_id}.incoming")
    if incoming_database.exists() or incoming_index.exists():
        raise FileExistsError(f"Incoming assets already exist for {release_id}")
    shutil.copy2(staged_database, incoming_database)
    shutil.copytree(staged_index, incoming_index)

    had_live_database = live_database.is_file()
    had_live_index = live_index.is_dir()
    database_backup: dict[str, object] | None = None
    if had_live_database:
        database_backup = backup_database(live_database, backup_directory)

    rollback_root = staged_database.parent / "rollback"
    rollback_root.mkdir(parents=True, exist_ok=True)
    rollback_index = rollback_root / "vector_index"
    failed_index = rollback_root / "failed_vector_index"
    failed_database = rollback_root / "failed_database.db"
    unpublished_index = rollback_root / "unpublished_vector_index"
    unpublished_database = rollback_root / "unpublished_database.db"
    database_replaced = False
    index_replaced = False
    try:
        if had_live_index:
            os.replace(live_index, rollback_index)
        os.replace(incoming_database, live_database)
        database_replaced = True
        os.replace(incoming_index, live_index)
        index_replaced = True
        expected_database_hash = str(
            dict(release_manifest["database"])["sha256"]
        )
        if sha256_file(live_database) != expected_database_hash:
            raise RuntimeError("Published database checksum does not match staged release")
        if _index_hashes(live_index) != dict(release_manifest["index"])["file_sha256"]:
            raise RuntimeError("Published index checksums do not match staged release")

        published = {
            **release_manifest,
            "status": "published",
            "published_at": datetime.now(UTC).isoformat(),
            "live_database": str(live_database),
            "live_index": str(live_index),
            "database_backup": database_backup,
            "rollback_index": str(rollback_index) if had_live_index else None,
        }
        manifest_path = release_directory / f"{release_id}.json"
        _write_json(manifest_path, published)
        return {**published, "manifest_path": str(manifest_path)}
    except Exception:
        if index_replaced and live_index.exists():
            os.replace(live_index, failed_index)
        if had_live_index and rollback_index.exists():
            os.replace(rollback_index, live_index)
        if database_replaced:
            if had_live_database and database_backup is not None:
                recovery = rollback_root / "database_recovery.incoming"
                shutil.copy2(Path(str(database_backup["backup_path"])), recovery)
                os.replace(recovery, live_database)
            elif live_database.exists():
                os.replace(live_database, failed_database)
        if incoming_index.exists():
            os.replace(incoming_index, unpublished_index)
        if incoming_database.exists():
            os.replace(incoming_database, unpublished_database)
        raise


def execute_refresh(
    *,
    live_database: Path = DEFAULT_DATABASE_PATH,
    live_index: Path = VECTOR_INDEX_PATH,
    staging_root: Path | None = None,
    backup_directory: Path | None = None,
    release_directory: Path | None = None,
    lock_path: Path | None = None,
    embedding_backend: str = "sentence-transformers",
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    embedding_dimension: int = 384,
    pubmed_max: int = 200,
    trial_page_size: int = 100,
    trial_max_pages: int = 20,
    adcdb_limit: int = 10,
    skip_pubmed: bool = False,
    skip_trials: bool = False,
    skip_adcdb: bool = False,
    source_retries: int = 3,
    source_retry_delay: float = 1.0,
    max_count_drop_ratio: float = 0.25,
    max_missing_records: int = 0,
    refresh_id: str | None = None,
    pipeline_runner: Callable[[Namespace], dict[str, object]] = run_pipeline,
) -> dict[str, object]:
    """Collect into staging, gate, index, back up and promote one release."""
    live_database = Path(live_database)
    live_index = Path(live_index)
    staging_root = staging_root or live_database.parent / "refresh_staging"
    backup_directory = backup_directory or live_database.parent / "backups"
    release_directory = release_directory or live_database.parent / "releases"
    lock_path = lock_path or live_database.parent / "refresh.lock"
    release_id = refresh_id or _refresh_id()
    stage = Path(staging_root) / release_id
    staged_database = stage / "adc_evidence.db"
    staged_index = stage / "vector_index"
    staged_raw = stage / "raw"
    staged_quality = stage / "data_quality_report.json"

    with RefreshLock(Path(lock_path)):
        if stage.exists():
            raise FileExistsError(f"Refresh stage already exists: {stage}")
        stage.mkdir(parents=True)
        if live_database.is_file():
            _sqlite_copy(live_database, staged_database)
        else:
            create_database(staged_database)

        pipeline_args = Namespace(
            run_id=release_id,
            database=staged_database,
            raw_root=staged_raw,
            quality_report=staged_quality,
            pubmed_max=pubmed_max,
            trial_page_size=trial_page_size,
            trial_max_pages=trial_max_pages,
            adcdb_limit=adcdb_limit,
            skip_pubmed=skip_pubmed,
            skip_trials=skip_trials,
            skip_adcdb=skip_adcdb,
            strict=False,
            source_retries=source_retries,
            source_retry_delay=source_retry_delay,
        )
        run_summary = pipeline_runner(pipeline_args)
        required_sources = tuple(
            source
            for source, skipped in (
                ("adcdb", skip_adcdb),
                ("clinicaltrials", skip_trials),
                ("pubmed", skip_pubmed),
            )
            if not skipped
        )
        gate_report = evaluate_refresh_gates(
            staged_database,
            release_id,
            required_sources=required_sources,
            max_count_drop_ratio=max_count_drop_ratio,
            max_missing_records=max_missing_records,
        )
        _write_json(stage / "quality_gate_report.json", gate_report)
        if not bool(gate_report["passed"]):
            rejected = {
                "release_id": release_id,
                "run_id": release_id,
                "status": "rejected",
                "created_at": datetime.now(UTC).isoformat(),
                "staging_directory": str(stage),
                "database_sha256": sha256_file(staged_database),
                "quality_gates": gate_report,
                "run_summary": run_summary,
            }
            _write_json(stage / "release_manifest.json", rejected)
            return {**rejected, "published": False}

        documents = build_retrieval_documents(staged_database)
        chunks = chunk_documents(documents)
        corpus_summary = persist_retrieval_corpus_incremental(
            staged_database,
            documents,
            chunks,
        )
        build_vector_index(
            database_path=staged_database,
            index_path=staged_index,
            backend=embedding_backend,
            model_name=embedding_model,
            dimension=embedding_dimension,
        )
        load_vector_index(staged_index, database_path=staged_database)
        manifest = build_release_manifest(
            release_id=release_id,
            run_id=str(run_summary["run_id"]),
            database_path=staged_database,
            index_path=staged_index,
            gate_report=gate_report,
            corpus_summary=corpus_summary,
        )
        manifest["staging_directory"] = str(stage)
        _write_json(stage / "release_manifest.json", manifest)
        published = publish_staged_assets(
            staged_database=staged_database,
            staged_index=staged_index,
            live_database=live_database,
            live_index=live_index,
            backup_directory=Path(backup_directory),
            release_directory=Path(release_directory),
            release_manifest=manifest,
        )
        return {**published, "published": True}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely refresh and publish ADC-Evidence data and indexes."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--index", type=Path, default=VECTOR_INDEX_PATH)
    parser.add_argument("--staging-root", type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--release-dir", type=Path)
    parser.add_argument("--lock-path", type=Path)
    parser.add_argument(
        "--backend",
        choices=("sentence-transformers", "hashing"),
        default="sentence-transformers",
    )
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--dimension", type=int, default=384)
    parser.add_argument("--pubmed-max", type=int, default=200)
    parser.add_argument("--trial-page-size", type=int, default=100)
    parser.add_argument("--trial-max-pages", type=int, default=20)
    parser.add_argument("--adcdb-limit", type=int, default=10)
    parser.add_argument("--skip-pubmed", action="store_true")
    parser.add_argument("--skip-trials", action="store_true")
    parser.add_argument("--skip-adcdb", action="store_true")
    parser.add_argument("--source-retries", type=int, default=3)
    parser.add_argument("--source-retry-delay", type=float, default=1.0)
    parser.add_argument("--max-count-drop-ratio", type=float, default=0.25)
    parser.add_argument("--max-missing-records", type=int, default=0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = execute_refresh(
        live_database=args.database,
        live_index=args.index,
        staging_root=args.staging_root,
        backup_directory=args.backup_dir,
        release_directory=args.release_dir,
        lock_path=args.lock_path,
        embedding_backend=args.backend,
        embedding_model=args.model,
        embedding_dimension=args.dimension,
        pubmed_max=args.pubmed_max,
        trial_page_size=args.trial_page_size,
        trial_max_pages=args.trial_max_pages,
        adcdb_limit=args.adcdb_limit,
        skip_pubmed=args.skip_pubmed,
        skip_trials=args.skip_trials,
        skip_adcdb=args.skip_adcdb,
        source_retries=args.source_retries,
        source_retry_delay=args.source_retry_delay,
        max_count_drop_ratio=args.max_count_drop_ratio,
        max_missing_records=args.max_missing_records,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not bool(result["published"]):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
