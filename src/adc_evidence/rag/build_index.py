from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.config import DEFAULT_DATABASE_PATH, DEFAULT_EMBEDDING_MODEL, VECTOR_INDEX_PATH
from adc_evidence.rag.documents import build_and_persist_corpus
from adc_evidence.rag.vector_index import build_vector_index


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the ADC-Evidence retrieval corpus and indexes.")
    parser.add_argument(
        "--backend",
        choices=("sentence-transformers", "hashing"),
        default="sentence-transformers",
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--index-path", type=Path, default=VECTOR_INDEX_PATH)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--max-chars", type=int, default=1200)
    parser.add_argument("--overlap-chars", type=int, default=160)
    args = parser.parse_args()

    document_count, chunk_count = build_and_persist_corpus(
        database_path=args.database,
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
    )
    manifest = build_vector_index(
        database_path=args.database,
        index_path=args.index_path,
        backend=args.backend,
        model_name=args.model,
    )
    print(
        json.dumps(
            {
                "retrieval_document_count": document_count,
                "text_chunk_count": chunk_count,
                **manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
