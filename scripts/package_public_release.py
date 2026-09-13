"""Package a verified public database and retrieval index for direct download.

The archive is an external release artifact. SQLite, raw responses and index
files remain ignored by Git; this command only packages files the caller has
explicitly selected and records their checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from adc_evidence.rag.documents import retrieval_corpus_version


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "processed" / "adc_public_2026-09-30.db"
DEFAULT_INDEX = ROOT / "artifacts" / "vector_index" / "public_2026-09-30"
DEFAULT_CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_CATALOG_AUDIT = ROOT / "data" / "public" / "marketed_adc_catalog.audit.json"
DEFAULT_BENCHMARK = ROOT / "data" / "annotations" / "public_benchmark_v1.manifest.json"
DEFAULT_BENCHMARK_QUESTIONS = ROOT / "data" / "annotations" / "public_benchmark_v1.jsonl"
DEFAULT_OUTPUT = ROOT / "artifacts" / "releases" / "adc-public-2026-09-30.zip"


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


def build_release_inventory(
    *,
    database: Path,
    index_path: Path,
    catalog: Path,
    benchmark_manifest: Path,
    as_of: str,
    catalog_audit: Path | None = None,
    benchmark_questions: Path | None = None,
) -> tuple[list[tuple[Path, str]], dict[str, object]]:
    database = _require_file(database, "database")
    catalog = _require_file(catalog, "catalog")
    if catalog_audit is not None:
        catalog_audit = _require_file(catalog_audit, "catalog audit")
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
        (database, f"data/processed/{database.name}"),
        (catalog, f"data/public/{catalog.name}"),
    ]
    if catalog_audit is not None:
        files.append((catalog_audit, f"data/public/{catalog_audit.name}"))
    files.extend([
        (benchmark_manifest, f"data/annotations/{benchmark_manifest.name}"),
    ])
    if benchmark_questions is not None:
        files.append((benchmark_questions, f"data/annotations/{benchmark_questions.name}"))
    files.extend(
        (path, f"artifacts/vector_index/{index_path.name}/{path.relative_to(index_path).as_posix()}")
        for path in _index_files(index_path)
    )
    inventory = {
        "schema_version": "public-adc-release-v1",
        "dataset_as_of": as_of,
        "retrieval_corpus_version": corpus_version,
        "benchmark_manifest": _read_json(benchmark_manifest),
        "files": [
            {"archive_path": archive_path, "size_bytes": path.stat().st_size, "sha256": _sha256(path)}
            for path, archive_path in files
        ],
        "redistribution_note": "Verify source licenses for abstracts and trial payloads before redistribution.",
    }
    return files, inventory


def _release_readme(as_of: str) -> str:
    return f"""# ADC-Evidence public release ({as_of})

This archive contains a public SQLite snapshot, its matching retrieval index,
the public ADC catalog and its source audit, the benchmark questions and manifest. `RELEASE_MANIFEST.json`
binds every file to a SHA-256 checksum.

After extracting at the repository root, configure:

```powershell
$env:ADC_DATABASE_PATH = "data/processed/adc_public_{as_of}.db"
$env:ADC_SEED_PATH = "data/public/marketed_adc_catalog.csv"
$env:ADC_VECTOR_INDEX_PATH = "artifacts/vector_index/public_{as_of}"
streamlit run src/adc_evidence/app.py
```

Abstract and full-text redistribution remains subject to the original source
license. Use the catalog builder to reproduce or refresh the snapshot.
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
    benchmark_questions: Path | None = None,
) -> dict[str, object]:
    files, inventory = build_release_inventory(
        database=database,
        index_path=index_path,
        catalog=catalog,
        catalog_audit=catalog_audit,
        benchmark_manifest=benchmark_manifest,
        benchmark_questions=benchmark_questions,
        as_of=as_of,
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
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
        archive.writestr(readme_info, _release_readme(as_of))
    return {"output": str(output), "size_bytes": output.stat().st_size, **inventory}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--catalog-audit", type=Path, default=DEFAULT_CATALOG_AUDIT)
    parser.add_argument("--benchmark-manifest", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--benchmark-questions", type=Path, default=DEFAULT_BENCHMARK_QUESTIONS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", default="2026-09-30")
    args = parser.parse_args()
    result = package_release(
        database=args.database,
        index_path=args.index_path,
        catalog=args.catalog,
        catalog_audit=args.catalog_audit,
        benchmark_manifest=args.benchmark_manifest,
        benchmark_questions=args.benchmark_questions,
        output=args.output,
        as_of=args.as_of,
    )
    print(json.dumps({key: result[key] for key in ("output", "size_bytes", "dataset_as_of", "retrieval_corpus_version")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
