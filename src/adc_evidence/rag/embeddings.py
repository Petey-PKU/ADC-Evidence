from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Protocol, Sequence

import numpy as np


class Embedder(Protocol):
    backend_name: str
    model_name: str
    dimension: int

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray: ...

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray: ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.maximum(norms, 1e-12)


@dataclass
class HashingEmbedder:
    """Dependency-free test backend; not a replacement for semantic embeddings."""

    dimension: int = 384
    backend_name: str = "hashing"
    model_name: str = "sha256-token-hashing-v1"

    @staticmethod
    def _tokens(text: str) -> list[str]:
        normalized = text.casefold().replace("-", " ")
        latin = re.findall(r"[a-z0-9]+", normalized)
        chinese = re.findall(r"[\u4e00-\u9fff]", normalized)
        return latin + chinese

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row_index, text in enumerate(texts):
            for token in self._tokens(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                index = int.from_bytes(digest[:4], "little") % self.dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                matrix[row_index, index] += sign
        return _normalize(matrix)

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts)


class SentenceTransformerEmbedder:
    backend_name = "sentence-transformers"

    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise RuntimeError(
                "Dense retrieval requires the optional RAG dependencies. "
                "Run: python -m pip install -e '.[rag]'"
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        dimension_method = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        self.dimension = int(dimension_method())

    def _encode(self, texts: Sequence[str], *, query: bool) -> np.ndarray:
        method_name = "encode_query" if query else "encode_document"
        method = getattr(self._model, method_name, self._model.encode)
        vectors = method(
            list(texts),
            batch_size=32,
            show_progress_bar=len(texts) > 64,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, query=False)

    def encode_queries(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, query=True)


def create_embedder(backend: str, model_name: str, dimension: int = 384) -> Embedder:
    if backend == "hashing":
        return HashingEmbedder(dimension=dimension)
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name)
    raise ValueError(f"Unknown embedding backend: {backend}")
