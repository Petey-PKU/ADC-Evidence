from __future__ import annotations

import json
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_EMBEDDING_MODEL,
    VECTOR_INDEX_PATH,
)
from adc_evidence.database import connect
from adc_evidence.rag.embeddings import Embedder, create_embedder


@dataclass(frozen=True)
class VectorIndex:
    embeddings: np.ndarray
    chunk_ids: list[str]
    manifest: dict[str, object]

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        if self.embeddings.shape[0] == 0:
            return []
        scores = self.embeddings @ np.asarray(query_vector, dtype=np.float32)
        candidate_count = min(max(top_k, 0), len(self.chunk_ids))
        if candidate_count == 0:
            return []
        indices = np.argpartition(-scores, candidate_count - 1)[:candidate_count]
        ordered = indices[np.argsort(-scores[indices])]
        return [(self.chunk_ids[int(index)], float(scores[int(index)])) for index in ordered]


def _corpus_rows(database_path: Path) -> list[tuple[str, str, str]]:
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT chunk_id, title, content FROM text_chunks ORDER BY chunk_id"
        ).fetchall()
    return [(str(row[0]), str(row[1]), str(row[2])) for row in rows]


def build_vector_index(
    database_path: Path = DEFAULT_DATABASE_PATH,
    index_path: Path = VECTOR_INDEX_PATH,
    *,
    backend: str = "sentence-transformers",
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    dimension: int = 384,
) -> dict[str, object]:
    rows = _corpus_rows(database_path)
    if not rows:
        raise RuntimeError("No text chunks found. Build the retrieval corpus first.")
    embedder = create_embedder(backend, model_name, dimension)
    texts = [f"{title}\n{content}" for _, title, content in rows]
    embeddings = embedder.encode_documents(texts)
    chunk_ids = [chunk_id for chunk_id, _, _ in rows]

    index_path.mkdir(parents=True, exist_ok=True)
    np.save(index_path / "embeddings.npy", embeddings, allow_pickle=False)
    (index_path / "chunk_ids.json").write_text(
        json.dumps(chunk_ids, ensure_ascii=False), encoding="utf-8"
    )
    manifest: dict[str, object] = {
        "index_type": "exact_cosine_numpy",
        "embedding_backend": embedder.backend_name,
        "embedding_model": embedder.model_name,
        "dimension": int(embeddings.shape[1]),
        "chunk_count": len(chunk_ids),
        "built_at": datetime.now(timezone.utc).isoformat(),
    }
    (index_path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def load_vector_index(index_path: Path = VECTOR_INDEX_PATH) -> VectorIndex:
    manifest = json.loads((index_path / "manifest.json").read_text(encoding="utf-8"))
    chunk_ids = json.loads((index_path / "chunk_ids.json").read_text(encoding="utf-8"))
    embeddings = np.load(index_path / "embeddings.npy", allow_pickle=False)
    if embeddings.shape[0] != len(chunk_ids):
        raise RuntimeError("Vector index is inconsistent: vector and chunk counts differ.")
    return VectorIndex(embeddings=embeddings, chunk_ids=chunk_ids, manifest=manifest)


def embedder_for_index(index: VectorIndex) -> Embedder:
    return create_embedder(
        str(index.manifest["embedding_backend"]),
        str(index.manifest["embedding_model"]),
        int(index.manifest["dimension"]),
    )
