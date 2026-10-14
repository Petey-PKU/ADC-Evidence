from __future__ import annotations

import json
import hashlib
import os
import shutil
import zipfile
from contextlib import closing
from pathlib import Path

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED_PATH,
    PUBLIC_DATABASE_ARCHIVE_PATH,
    PUBLIC_DATABASE_FILENAME,
    PUBLIC_DATABASE_SHA256,
    VECTOR_INDEX_PATH,
    environment_flag,
)
from adc_evidence.database import connect, create_database, initialize_database
from adc_evidence.rag.documents import build_and_persist_corpus, retrieval_corpus_version
from adc_evidence.rag.vector_index import build_vector_index
from adc_evidence.workbench import sync_public_seed_facts


def restore_public_snapshot_archive(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    archive_path: Path = PUBLIC_DATABASE_ARCHIVE_PATH,
) -> dict[str, object]:
    """Restore the tracked public snapshot archive into its runtime path."""
    database_path = Path(database_path)
    archive_path = Path(archive_path)
    if database_path.exists() or not archive_path.is_file():
        return {"restored": False, "archive": str(archive_path)}
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = database_path.with_name(f".{database_path.name}.incoming")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = [name for name in archive.namelist() if name == PUBLIC_DATABASE_FILENAME]
            if names != [PUBLIC_DATABASE_FILENAME]:
                raise RuntimeError(
                    f"Public snapshot archive must contain exactly {PUBLIC_DATABASE_FILENAME}."
                )
            digest_builder = hashlib.sha256()
            with archive.open(PUBLIC_DATABASE_FILENAME) as source, temporary_path.open("wb") as target:
                while chunk := source.read(1024 * 1024):
                    digest_builder.update(chunk)
                    target.write(chunk)
        digest = digest_builder.hexdigest()
        if digest != PUBLIC_DATABASE_SHA256:
            raise RuntimeError(
                "Public snapshot archive checksum mismatch; refusing to start with an unverified database."
            )
        os.replace(temporary_path, database_path)
        return {
            "restored": True,
            "archive": str(archive_path),
            "database": str(database_path),
            "sha256": digest,
        }
    finally:
        temporary_path.unlink(missing_ok=True)


def ensure_runtime_assets(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    seed_path: Path = DEFAULT_SEED_PATH,
    index_path: Path = VECTOR_INDEX_PATH,
    bootstrap_backend: str = "hashing",
    allow_seed_bootstrap: bool | None = None,
) -> dict[str, object]:
    """Validate or bootstrap the configured database and retrieval assets.

    The public runtime defaults to the tracked public snapshot archive. It is
    never silently replaced by the ten-row demo seed. Seed bootstrapping remains
    available for an explicitly supplied development/test database, or when
    ``ADC_BOOTSTRAP_DEMO=true`` is set deliberately.
    """
    database_path = Path(database_path)
    seed_path = Path(seed_path)
    index_path = Path(index_path)
    is_default_database = database_path.resolve() == DEFAULT_DATABASE_PATH.resolve()
    if allow_seed_bootstrap is None:
        allow_seed_bootstrap = (
            not is_default_database
            or environment_flag("ADC_BOOTSTRAP_DEMO", default=False)
        )
    archive_restore: dict[str, object] = {"restored": False}
    if is_default_database and not database_path.exists() and not allow_seed_bootstrap:
        archive_restore = restore_public_snapshot_archive(
            database_path=database_path,
            archive_path=PUBLIC_DATABASE_ARCHIVE_PATH,
        )
    if is_default_database and not database_path.exists() and not allow_seed_bootstrap:
        raise FileNotFoundError(
            "The configured public database is missing: "
            f"{database_path}. The tracked public snapshot archive was not found. "
            "Restore the repository data archive before starting. "
            "For an isolated demo only, set ADC_DATABASE_PATH to a separate "
            "development path and ADC_BOOTSTRAP_DEMO=true."
        )
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        adc_count = int(connection.execute("SELECT COUNT(*) FROM adcs").fetchone()[0])
    if adc_count == 0:
        if not allow_seed_bootstrap:
            raise RuntimeError(
                "The configured public database is empty. The v0.7 runtime "
                "requires the full public snapshot; it will not create the "
                "ten-record demo database automatically."
            )
        initialize_database(database_path, seed_path)
        with closing(connect(database_path)) as connection:
            adc_count = int(
                connection.execute("SELECT COUNT(*) FROM adcs").fetchone()[0]
            )
    if is_default_database and not allow_seed_bootstrap:
        with closing(connect(database_path)) as connection:
            document_count = int(
                connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            )
            trial_count = int(
                connection.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
            )
        if adc_count <= 10 or document_count == 0 or trial_count == 0:
            raise RuntimeError(
                "The configured public database does not look like the v0.7 "
                "public snapshot (expected more than the ten-record demo plus "
                "literature and trial records). Check ADC_DATABASE_PATH."
            )
    if allow_seed_bootstrap:
        seed_fact_sync: dict[str, object] = sync_public_seed_facts(
            database_path, seed_path
        )
    else:
        seed_fact_sync = {
            "adc_count": adc_count,
            "facts_created": 0,
            "evidence_created": 0,
            "change_events_created": 0,
            "idempotent_groups": 0,
            "skipped": True,
        }

    with closing(connect(database_path)) as connection:
        chunk_count = int(
            connection.execute("SELECT COUNT(*) FROM text_chunks").fetchone()[0]
        )
    corpus_built = False
    if chunk_count == 0:
        _, chunk_count = build_and_persist_corpus(database_path)
        corpus_built = True

    manifest_path = index_path / "manifest.json"
    index_built = False
    index_is_current = False
    if manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        index_is_current = (
            existing_manifest.get("retrieval_corpus_version")
            == retrieval_corpus_version(database_path)
        )
    if not index_is_current:
        build_vector_index(
            database_path=database_path,
            index_path=index_path,
            backend=bootstrap_backend,
        )
        index_built = True
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "adc_count": adc_count,
        "chunk_count": chunk_count,
        "corpus_built": corpus_built,
        "index_built": index_built,
        "embedding_backend": manifest["embedding_backend"],
        "public_snapshot_restore": archive_restore,
        "seed_fact_sync": seed_fact_sync,
    }


def main() -> None:
    backend = os.getenv("ADC_BOOTSTRAP_EMBEDDING_BACKEND", "hashing")
    if backend not in {"hashing", "sentence-transformers"}:
        raise ValueError(
            "ADC_BOOTSTRAP_EMBEDDING_BACKEND must be hashing or sentence-transformers"
        )
    summary = ensure_runtime_assets(bootstrap_backend=backend)
    print(json.dumps({"runtime_assets": summary}, ensure_ascii=False), flush=True)
    port = os.getenv("PORT", "8501")
    os.execvp(
        "streamlit",
        [
            "streamlit",
            "run",
            "src/adc_evidence/app.py",
            "--server.address=0.0.0.0",
            f"--server.port={port}",
            "--server.headless=true",
        ],
    )


if __name__ == "__main__":
    main()
