from __future__ import annotations

import argparse
import json
import re
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path

from adc_evidence.config import DEFAULT_DATABASE_PATH, VECTOR_INDEX_PATH
from adc_evidence.database import connect
from adc_evidence.processing.normalize import EntityNormalizer
from adc_evidence.rag.query_expansion import expand_query
from adc_evidence.rag.vector_index import embedder_for_index, load_vector_index


@dataclass(frozen=True)
class SearchResult:
    rank: int
    chunk_id: str
    retrieval_document_id: str
    source_type: str
    source_record_id: str
    title: str
    content: str
    source_url: str
    score: float
    metadata: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _fts_expression(query: str) -> str:
    expanded = expand_query(query)
    tokens = re.findall(r"[A-Za-z0-9]+(?:[.+][A-Za-z0-9]+)*|[\u4e00-\u9fff]{2,}", expanded)
    deduplicated = list(dict.fromkeys(token.casefold() for token in tokens if len(token) > 1))
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in deduplicated)


class HybridRetriever:
    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE_PATH,
        index_path: Path = VECTOR_INDEX_PATH,
    ) -> None:
        self.database_path = Path(database_path)
        self.index_path = Path(index_path)
        self._vector_index = None
        self._embedder = None
        self._entity_normalizer = EntityNormalizer()

    @property
    def dense_available(self) -> bool:
        return all(
            (self.index_path / name).exists()
            for name in ("manifest.json", "chunk_ids.json", "embeddings.npy")
        )

    def _load_dense(self) -> None:
        if self._vector_index is None:
            self._vector_index = load_vector_index(self.index_path)
            self._embedder = embedder_for_index(self._vector_index)

    def _row_to_result(self, row, score: float, rank: int) -> SearchResult:
        metadata = json.loads(row["metadata_json"])
        return SearchResult(
            rank=rank,
            chunk_id=str(row["chunk_id"]),
            retrieval_document_id=str(row["retrieval_document_id"]),
            source_type=str(row["source_type"]),
            source_record_id=str(row["source_record_id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            source_url=str(row["source_url"]),
            score=float(score),
            metadata=metadata,
        )

    def sparse_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        source_type: str | None = None,
        adc_id: str | None = None,
    ) -> list[SearchResult]:
        expression = _fts_expression(query)
        if not expression:
            return []
        filters = ["text_chunks_fts MATCH ?"]
        parameters: list[object] = [expression]
        if source_type:
            filters.append("document.source_type = ?")
            parameters.append(source_type)
        if adc_id:
            filters.append("chunk.metadata_json LIKE ?")
            parameters.append(f'%"{adc_id}"%')
        candidate_limit = max(top_k * 10, 60)
        parameters.append(candidate_limit)
        sql = f"""
            SELECT chunk.*, document.source_type, document.source_record_id,
                   document.source_url, bm25(text_chunks_fts, 2.0, 1.0, 0.8) AS bm25_score
            FROM text_chunks_fts
            JOIN text_chunks AS chunk ON chunk.chunk_id = text_chunks_fts.chunk_id
            JOIN retrieval_documents AS document
              ON document.retrieval_document_id = chunk.retrieval_document_id
            WHERE {' AND '.join(filters)}
            ORDER BY bm25_score
            LIMIT ?
        """
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(sql, parameters).fetchall()
        matched_adc_ids = {
            match.entity_id
            for match in self._entity_normalizer.find_matches(query, entity_types=("adc",))
        }
        scored_rows = [(row, -float(row["bm25_score"])) for row in rows]

        def ranking_key(item) -> tuple[bool, float]:
            row, score = item
            metadata = json.loads(row["metadata_json"])
            linked_adc_ids = set(metadata.get("adc_ids", []))
            return bool(matched_adc_ids & linked_adc_ids), score

        scored_rows.sort(key=ranking_key, reverse=True)
        results: list[SearchResult] = []
        seen_documents: set[str] = set()
        for row, score in scored_rows:
            document_id = str(row["retrieval_document_id"])
            if document_id in seen_documents:
                continue
            seen_documents.add(document_id)
            results.append(self._row_to_result(row, score, len(results) + 1))
            if len(results) == top_k:
                break
        return results

    def dense_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        source_type: str | None = None,
        adc_id: str | None = None,
    ) -> list[SearchResult]:
        if not self.dense_available:
            raise RuntimeError("Vector index not found. Run the index builder first.")
        self._load_dense()
        assert self._vector_index is not None and self._embedder is not None
        vector = self._embedder.encode_queries([query])[0]
        ranked = self._vector_index.search(vector, len(self._vector_index.chunk_ids))
        scores = dict(ranked)

        filters: list[str] = []
        parameters: list[object] = []
        if source_type:
            filters.append("document.source_type = ?")
            parameters.append(source_type)
        if adc_id:
            filters.append("chunk.metadata_json LIKE ?")
            parameters.append(f'%"{adc_id}"%')
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with closing(connect(self.database_path)) as connection:
            rows = connection.execute(
                f"""
                SELECT chunk.*, document.source_type, document.source_record_id,
                       document.source_url
                FROM text_chunks AS chunk
                JOIN retrieval_documents AS document
                  ON document.retrieval_document_id = chunk.retrieval_document_id
                {where}
                """,
                parameters,
            ).fetchall()
        rows_by_id = {str(row["chunk_id"]): row for row in rows}
        results: list[SearchResult] = []
        seen_documents: set[str] = set()
        for chunk_id, _ in ranked:
            row = rows_by_id.get(chunk_id)
            if row is None:
                continue
            document_id = str(row["retrieval_document_id"])
            if document_id in seen_documents:
                continue
            seen_documents.add(document_id)
            results.append(
                self._row_to_result(row, scores[chunk_id], len(results) + 1)
            )
            if len(results) == top_k:
                break
        return results

    def hybrid_search(
        self,
        query: str,
        *,
        top_k: int = 10,
        source_type: str | None = None,
        adc_id: str | None = None,
        candidate_k: int = 60,
        sparse_weight: float = 6.0,
        dense_weight: float = 1.0,
    ) -> list[SearchResult]:
        sparse = self.sparse_search(
            query,
            top_k=candidate_k,
            source_type=source_type,
            adc_id=adc_id,
        )
        dense = self.dense_search(
            query,
            top_k=candidate_k,
            source_type=source_type,
            adc_id=adc_id,
        )
        by_document: dict[str, SearchResult] = {}
        fused: dict[str, float] = {}
        for results, weight in ((sparse, sparse_weight), (dense, dense_weight)):
            for rank, result in enumerate(results, start=1):
                document_id = result.retrieval_document_id
                by_document.setdefault(document_id, result)
                fused[document_id] = fused.get(document_id, 0.0) + weight / (60 + rank)
        ranked_ids = sorted(fused, key=fused.get, reverse=True)[:top_k]
        return [
            SearchResult(
                **{
                    **by_document[document_id].to_dict(),
                    "rank": rank,
                    "score": fused[document_id],
                }
            )
            for rank, document_id in enumerate(ranked_ids, start=1)
        ]

    def search(self, query: str, *, mode: str = "hybrid", **kwargs) -> list[SearchResult]:
        if mode == "sparse":
            return self.sparse_search(query, **kwargs)
        if mode == "dense":
            return self.dense_search(query, **kwargs)
        if mode == "hybrid":
            return self.hybrid_search(query, **kwargs)
        raise ValueError(f"Unknown retrieval mode: {mode}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search the ADC-Evidence retrieval index.")
    parser.add_argument("query")
    parser.add_argument("--mode", choices=("sparse", "dense", "hybrid"), default="hybrid")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--source-type", choices=("adc_profile", "pubmed", "clinical_trial"))
    parser.add_argument("--adc-id")
    args = parser.parse_args()
    results = HybridRetriever().search(
        args.query,
        mode=args.mode,
        top_k=args.top_k,
        source_type=args.source_type,
        adc_id=args.adc_id,
    )
    print(json.dumps([item.to_dict() for item in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
