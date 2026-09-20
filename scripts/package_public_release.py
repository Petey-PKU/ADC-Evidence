"""Package a verified public database and retrieval index for direct download.

The archive is an external release artifact. SQLite, raw responses and index
files remain ignored by Git; this command only packages files the caller has
explicitly selected and records their checksums.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
import zipfile
from pathlib import Path

from adc_evidence.rag.documents import retrieval_corpus_version
from adc_evidence.evaluation.public_hygiene import scan_public_text


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "processed" / "adc_public_2026-09-30.db"
DEFAULT_INDEX = ROOT / "artifacts" / "vector_index" / "public_2026-09-30"
DEFAULT_CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_CATALOG_AUDIT = ROOT / "data" / "public" / "marketed_adc_catalog.audit.json"
DEFAULT_SCOPE_POLICY = ROOT / "data" / "public" / "catalog_scope_policy.json"
DEFAULT_CANDIDATE_LOCATORS = ROOT / "data" / "public" / "catalog_source_locator_candidates.jsonl"
DEFAULT_BENCHMARK = ROOT / "data" / "annotations" / "public_benchmark_v1.manifest.json"
DEFAULT_BENCHMARK_QUESTIONS = ROOT / "data" / "annotations" / "public_benchmark_v1.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "releases" / "adc-public-2026-09-30.zip"


def _runtime_files() -> tuple[list[tuple[Path, str]], dict[str, object]]:
    """Bundle only tracked public application files, never local caches/config."""
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0"))
    required = {
        "pyproject.toml", "README.md", "configs/entities.json", "configs/evidence_policy.json",
        "scripts/run_public_release.py", "scripts/verify_public_release.py",
        "src/adc_evidence/__init__.py", "src/adc_evidence/app.py",
    }
    if missing := required - tracked:
        raise ValueError(f"Runtime files must be tracked before packaging: {sorted(missing)}")
    paths = sorted(required | {
        name for name in tracked if name.startswith("src/adc_evidence/") and name.endswith(".py")
    })
    files = []
    for name in paths:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT) or not path.is_file():
            raise ValueError(f"Invalid runtime source: {name}")
        if scan_public_text(name, path.read_text(encoding="utf-8")):
            raise ValueError(f"Public hygiene check failed for runtime source: {name}")
        files.append((path, name))
    metadata = {
        "mode": "bundled_source",
        "code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "code_worktree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)),
        "runtime_file_count": len(files),
        "launcher": "scripts/run_public_release.py",
        "python_requires": ">=3.11",
        "dependencies_bundled": False,
    }
    return files, metadata


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _require_file(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    return path


def _index_files(index_path: Path) -> list[Path]:
    required = ("manifest.json", "chunk_ids.json", "embeddings.npy")
    missing = [name for name in required if not (index_path / name).is_file()]
    if missing:
        raise FileNotFoundError(f"Index is incomplete: {', '.join(missing)}")
    return sorted(item for item in index_path.rglob("*") if item.is_file())


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _redistribution_metadata(
    *,
    attestation: Path | None,
    research_only: bool,
) -> dict[str, object]:
    """Require an explicit release mode before packaging source-derived text.

    A local research artifact may contain the snapshot for reproducibility, but
    it is not a redistribution approval. A public package needs a separate,
    content-free attestation; the attestation itself is never bundled.
    """
    if bool(attestation) == research_only:
        raise ValueError(
            "Choose exactly one release mode: --research-only or "
            "--redistribution-attestation"
        )
    if research_only:
        return {
            "status": "research_only",
            "redistribution_allowed": False,
            "reason": "No source-license attestation supplied; local validation only.",
        }
    attestation = _require_file(attestation, "redistribution attestation")
    value = _read_json(attestation)
    if value.get("schema_version") != "public-redistribution-attestation-v1":
        raise ValueError("Redistribution attestation has an unsupported schema_version")
    if value.get("status") != "approved":
        raise ValueError("Redistribution attestation must have status=approved")
    for field in ("attestation_id", "scope", "review_date"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ValueError(f"Redistribution attestation needs nonempty {field}")
    return {
        "status": "approved",
        "redistribution_allowed": True,
        "attestation_id": value["attestation_id"],
        "scope": value["scope"],
        "review_date": value["review_date"],
        "attestation_sha256": _sha256(attestation),
    }


def _dataset_summary(database: Path) -> dict[str, object]:
    """Read public, non-content counts without exposing raw paths or text."""
    uri = f"file:{database.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        connection.row_factory = sqlite3.Row
        counts: dict[str, int] = {}
        for name in ("adcs", "trials", "documents", "entity_links", "evidence"):
            counts[name] = int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        abstract_count = int(connection.execute(
            "SELECT COUNT(*) FROM documents WHERE abstract IS NOT NULL AND abstract <> ''"
        ).fetchone()[0])
        topic_counts = {
            str(row[0]): int(row[1])
            for row in connection.execute(
                "SELECT topic, COUNT(*) FROM literature_topics GROUP BY topic ORDER BY topic"
            ).fetchall()
        }
        latest = connection.execute(
            "SELECT run_id, started_at, finished_at, status FROM ingestion_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    document_count = counts["documents"]
    return {
        "schema_version": "public-adc-dataset-summary-v1",
        "counts": counts,
        "document_with_abstract_count": abstract_count,
        "abstract_coverage": round(abstract_count / document_count, 4) if document_count else 0.0,
        "literature_topic_counts": topic_counts,
        "latest_ingestion_run": dict(latest) if latest is not None else None,
    }


def _validate_database_catalog_binding(database: Path, catalog: Path) -> None:
    """Fail closed when the selected SQLite snapshot drifts from its catalog.

    A release contains both files. Comparing the overlapping ADC fields here
    prevents a manually packaged snapshot from silently serving stale source
    URLs or structured values after the checked-in catalog has changed.
    """
    with catalog.open(encoding="utf-8-sig", newline="") as handle:
        catalog_rows = {
            str(row.get("adc_id", "")).strip(): row
            for row in csv.DictReader(handle)
        }
    if not catalog_rows or any(not key for key in catalog_rows):
        raise ValueError("Catalog must contain nonempty adc_id values")
    connection = sqlite3.connect(database)
    try:
        connection.row_factory = sqlite3.Row
        db_rows = {
            str(row["adc_id"]): dict(row)
            for row in connection.execute("SELECT * FROM adcs")
        }
    finally:
        connection.close()
    if set(db_rows) != set(catalog_rows):
        missing = sorted(set(catalog_rows) - set(db_rows))
        extra = sorted(set(db_rows) - set(catalog_rows))
        raise ValueError(
            "Database/catalog ADC IDs differ; "
            f"missing_in_database={missing}, extra_in_database={extra}"
        )
    comparable_fields = (
        "adc_name", "target", "antibody", "linker_name", "linker_type",
        "payload_name", "payload_class", "dar", "indication",
        "development_status", "company", "source_url", "data_review_status",
    )
    mismatches: list[str] = []
    for adc_id in sorted(catalog_rows):
        catalog_row = catalog_rows[adc_id]
        db_row = db_rows[adc_id]
        for field in comparable_fields:
            expected = str(catalog_row.get(field, "") or "").strip()
            actual = str(db_row.get(field, "") or "").strip()
            if expected != actual:
                mismatches.append(f"{adc_id}.{field}")
    if mismatches:
        raise ValueError(
            "Database/catalog field binding drift detected: "
            + ", ".join(mismatches[:20])
            + (" ..." if len(mismatches) > 20 else "")
        )


def _redact_local_paths(value: object) -> object:
    """Remove machine-specific absolute paths from JSON run parameters."""
    if isinstance(value, dict):
        return {str(key): _redact_local_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_local_paths(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"(?:[A-Za-z]:[\\/]|/Users/|/home/|\\\\)[^\"']+", "<local-path-redacted>", value)
    return value


def _sanitize_database_for_release(source: Path, destination: Path) -> Path:
    """Copy a database and remove local filesystem paths from the copy only."""
    # The managed Windows sandbox can reject creating a new file with a
    # `.db` suffix. Stage as a neutral binary file, then rename it before
    # opening SQLite.
    staged = destination.with_suffix(destination.suffix + ".tmpbin")
    with source.open("rb") as source_handle, staged.open("wb") as destination_handle:
        shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
    shutil.copystat(source, staged)
    os.replace(staged, destination)
    connection = sqlite3.connect(destination)
    try:
        connection.row_factory = sqlite3.Row
        for table in ("source_records", "source_snapshots", "trials", "documents"):
            columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}
            if "raw_path" not in columns:
                continue
            rows = connection.execute(f"SELECT rowid, raw_path FROM {table}").fetchall()
            for row in rows:
                raw = str(row["raw_path"] or "")
                basename = re.split(r"[\\/]", raw)[-1] or "unavailable"
                connection.execute(
                    f"UPDATE {table} SET raw_path=? WHERE rowid=?",
                    (f"raw/{table}/{basename}", row["rowid"]),
                )
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ingestion_runs'").fetchone():
            rows = connection.execute("SELECT rowid, parameters_json FROM ingestion_runs").fetchall()
            for row in rows:
                try:
                    value = json.loads(str(row["parameters_json"]))
                    redacted = json.dumps(_redact_local_paths(value), ensure_ascii=False, sort_keys=True)
                except (TypeError, ValueError, json.JSONDecodeError):
                    redacted = "<local-parameters-redacted>"
                connection.execute(
                    "UPDATE ingestion_runs SET parameters_json=? WHERE rowid=?",
                    (redacted, row["rowid"]),
                )
        connection.commit()
    finally:
        connection.close()
    return destination


def build_release_inventory(
    *,
    database: Path,
    index_path: Path,
    catalog: Path,
    benchmark_manifest: Path,
    as_of: str,
    database_archive_name: str | None = None,
    catalog_audit: Path | None = None,
    scope_policy: Path | None = None,
    candidate_locators: Path | None = None,
    benchmark_questions: Path | None = None,
    redistribution_metadata: dict[str, object] | None = None,
) -> tuple[list[tuple[Path, str]], dict[str, object]]:
    if not isinstance(redistribution_metadata, dict):
        raise ValueError("redistribution_metadata is required before packaging")
    database = _require_file(database, "database")
    catalog = _require_file(catalog, "catalog")
    _validate_database_catalog_binding(database, catalog)
    if catalog_audit is not None:
        catalog_audit = _require_file(catalog_audit, "catalog audit")
    if scope_policy is not None:
        scope_policy = _require_file(scope_policy, "catalog scope policy")
    if candidate_locators is not None:
        candidate_locators = _require_file(candidate_locators, "catalog source locator candidates")
    benchmark_manifest = _require_file(benchmark_manifest, "benchmark manifest")
    if benchmark_questions is not None:
        benchmark_questions = _require_file(benchmark_questions, "benchmark questions")
    index_path = index_path.resolve()
    if not index_path.is_dir():
        raise FileNotFoundError(f"index not found: {index_path}")
    index_manifest = _read_json(_require_file(index_path / "manifest.json", "index manifest"))
    corpus_version = retrieval_corpus_version(database)
    if index_manifest.get("retrieval_corpus_version") != corpus_version:
        raise ValueError("Database and vector index use different retrieval corpus versions")

    files: list[tuple[Path, str]] = [
        (database, f"data/processed/{database_archive_name or database.name}"),
        (catalog, f"data/public/{catalog.name}"),
    ]
    if catalog_audit is not None:
        files.append((catalog_audit, f"data/public/{catalog_audit.name}"))
    if scope_policy is not None:
        files.append((scope_policy, f"data/public/{scope_policy.name}"))
    if candidate_locators is not None:
        files.append((candidate_locators, f"data/public/{candidate_locators.name}"))
    files.extend([
        (benchmark_manifest, f"data/annotations/{benchmark_manifest.name}"),
    ])
    if benchmark_questions is not None:
        files.append((benchmark_questions, f"data/annotations/{benchmark_questions.name}"))
    files.extend(
        (path, f"artifacts/vector_index/{index_path.name}/{path.relative_to(index_path).as_posix()}")
        for path in _index_files(index_path)
    )
    runtime_files, application = _runtime_files()
    files.extend(runtime_files)
    application.update({
        "database_path": f"data/processed/{database_archive_name or database.name}",
        "catalog_path": f"data/public/{catalog.name}",
        "scope_policy_path": f"data/public/{scope_policy.name}" if scope_policy is not None else None,
        "candidate_locator_path": f"data/public/{candidate_locators.name}" if candidate_locators is not None else None,
        "index_path": f"artifacts/vector_index/{index_path.name}",
    })
    inventory = {
        "schema_version": "public-adc-release-v2",
        "application": application,
        "dataset_as_of": as_of,
        "retrieval_corpus_version": corpus_version,
        "dataset_summary": _dataset_summary(database),
        "benchmark_manifest": _read_json(benchmark_manifest),
        "redistribution": redistribution_metadata,
        "files": [
            {"archive_path": archive_path, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path, archive_path in files
        ],
        "redistribution_note": (
            "This archive is for local research validation only. Do not redistribute."
            if redistribution_metadata.get("status") == "research_only"
            else "Redistribution scope is limited to the attached source-license attestation."
        ),
    }
    return files, inventory


def _release_readme(as_of: str, redistribution_status: str = "unverified") -> str:
    return f"""# ADC-Evidence public release ({as_of})

This archive contains the query application and required configuration, a public
SQLite snapshot, its matching retrieval index, the public ADC catalog, field-level
source locator candidates, source audit, scope policy, and the benchmark questions and manifest. `RELEASE_MANIFEST.json`
binds every file to a SHA-256 checksum.

Extract into a new folder. No Git clone, model account, or data rebuild is needed.
Python 3.11+ is required. Install base Python dependencies once (this installation
needs internet access unless you supply your own dependency wheelhouse):

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python scripts/run_public_release.py --check
.venv/Scripts/python scripts/run_public_release.py --question "T-DXd 的靶点和载荷是什么？"
.venv/Scripts/python scripts/run_public_release.py
```

On Linux/macOS replace `.venv/Scripts/python` with `.venv/bin/python`.
For the browser app, open http://127.0.0.1:8501 after launch.
The launcher selects `ADC_DATABASE_PATH`, `ADC_SEED_PATH` and
`ADC_VECTOR_INDEX_PATH` from this archive's manifest, regardless of the working
directory. It enforces `ADC_OFFLINE_ONLY=true` and `ADC_LLM_BACKEND = "extractive"`.
Queries use local data without a model API or model download. The source commit,
working-tree status and file hashes are recorded under `application` and `files`.

The dataset remains a partial, pending-review snapshot. A working query does not
establish clinical validity, full source coverage, or independent human review.
Release mode: `{redistribution_status}`. If this says `research_only`, the archive
must remain local and must not be uploaded or redistributed. Abstract and full-text
redistribution remains subject to the original source license. Raw response files are not included; local paths stored in the source
database are redacted in this archive. Use the catalog builder to reproduce or
refresh the snapshot in the public source repository.
"""


def package_release(
    *,
    database: Path,
    index_path: Path,
    catalog: Path,
    benchmark_manifest: Path,
    output: Path,
    as_of: str,
    catalog_audit: Path | None = None,
    scope_policy: Path | None = None,
    candidate_locators: Path | None = DEFAULT_CANDIDATE_LOCATORS,
    benchmark_questions: Path | None = None,
    redistribution_attestation: Path | None = None,
    research_only: bool = False,
) -> dict[str, object]:
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    redistribution_metadata = _redistribution_metadata(
        attestation=redistribution_attestation,
        research_only=research_only,
    )
    release_database = database
    cleanup_paths: list[Path] = []
    if database.is_file():
        # Keep the staging copy beside the output because managed Windows
        # sandboxes may deny writes inside newly-created temporary folders.
        release_database = output.parent / f"adc_release_{uuid.uuid4().hex}.db"
        cleanup_paths.extend((release_database, release_database.with_suffix(release_database.suffix + ".tmpbin")))
        _sanitize_database_for_release(database.resolve(), release_database)
    try:
        files, inventory = build_release_inventory(
            database=release_database,
            index_path=index_path,
            catalog=catalog,
            catalog_audit=catalog_audit,
            scope_policy=scope_policy,
            candidate_locators=candidate_locators,
            benchmark_manifest=benchmark_manifest,
            benchmark_questions=benchmark_questions,
            as_of=as_of,
            database_archive_name=database.name,
            redistribution_metadata=redistribution_metadata,
        )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path, archive_path in files:
                info = zipfile.ZipInfo(archive_path, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes())
            manifest_info = zipfile.ZipInfo("RELEASE_MANIFEST.json", date_time=(2020, 1, 1, 0, 0, 0))
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(manifest_info, json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            readme_info = zipfile.ZipInfo("RELEASE_README.md", date_time=(2020, 1, 1, 0, 0, 0))
            readme_info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                readme_info,
                _release_readme(as_of, str(redistribution_metadata["status"])),
            )
    finally:
        for path in cleanup_paths:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return {"output": str(output), "size_bytes": output.stat().st_size, **inventory}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--catalog-audit", type=Path, default=DEFAULT_CATALOG_AUDIT)
    parser.add_argument("--scope-policy", type=Path, default=DEFAULT_SCOPE_POLICY)
    parser.add_argument("--candidate-locators", type=Path, default=DEFAULT_CANDIDATE_LOCATORS)
    parser.add_argument("--benchmark-manifest", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--benchmark-questions", type=Path, default=DEFAULT_BENCHMARK_QUESTIONS)
    release_mode = parser.add_mutually_exclusive_group(required=True)
    release_mode.add_argument(
        "--research-only",
        action="store_true",
        help="Build a local validation artifact that must not be redistributed.",
    )
    release_mode.add_argument(
        "--redistribution-attestation",
        type=Path,
        help="Content-free JSON attestation approving the selected source content for redistribution.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", default="2026-09-30")
    args = parser.parse_args()
    result = package_release(
        database=args.database,
        index_path=args.index_path,
        catalog=args.catalog,
        catalog_audit=args.catalog_audit,
        scope_policy=args.scope_policy,
        candidate_locators=args.candidate_locators,
        benchmark_manifest=args.benchmark_manifest,
        benchmark_questions=args.benchmark_questions,
        redistribution_attestation=args.redistribution_attestation,
        research_only=args.research_only,
        output=args.output,
        as_of=args.as_of,
    )
    print(json.dumps({key: result[key] for key in ("output", "size_bytes", "dataset_as_of", "retrieval_corpus_version")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
