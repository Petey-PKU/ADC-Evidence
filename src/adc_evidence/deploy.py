from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED_PATH,
    VECTOR_INDEX_PATH,
)
from adc_evidence.database import connect, create_database, initialize_database
from adc_evidence.rag.documents import build_and_persist_corpus
from adc_evidence.rag.vector_index import build_vector_index


def ensure_runtime_assets(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    seed_path: Path = DEFAULT_SEED_PATH,
    index_path: Path = VECTOR_INDEX_PATH,
    bootstrap_backend: str = "hashing",
) -> dict[str, object]:
    """Create a runnable demo only when persisted assets are absent.

    Existing real data and vector indexes are never replaced. A clean deployment
    receives the ten-row seed database and a lightweight hashing index.
    """
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        adc_count = int(connection.execute("SELECT COUNT(*) FROM adcs").fetchone()[0])
    if adc_count == 0:
        initialize_database(database_path, seed_path)
        with closing(connect(database_path)) as connection:
            adc_count = int(
                connection.execute("SELECT COUNT(*) FROM adcs").fetchone()[0]
            )

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
    if not manifest_path.exists():
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
