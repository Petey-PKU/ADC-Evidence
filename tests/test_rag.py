from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from adc_evidence.database import create_database, initialize_database
from adc_evidence.rag.documents import (
    RetrievalDocument,
    build_retrieval_documents,
    chunk_documents,
    persist_retrieval_corpus,
    split_text,
)
from adc_evidence.rag.evaluate import _aggregate_review_status, _question_metrics
from adc_evidence.rag.retriever import HybridRetriever


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ChunkingTests(unittest.TestCase):
    def test_split_text_respects_maximum_size(self) -> None:
        text = f"{'A' * 100}.\n{'B' * 110}."
        chunks = split_text(text, max_chars=120, overlap_chars=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))

    def test_chunk_ids_are_deterministic(self) -> None:
        document = RetrievalDocument(
            retrieval_document_id="pubmed:1",
            source_type="pubmed",
            source_record_id="1",
            title="Example",
            content="A sentence. Another sentence.",
            source_url="https://example.test/1",
            metadata={},
        )
        first = chunk_documents([document], max_chars=20, overlap_chars=5)
        second = chunk_documents([document], max_chars=20, overlap_chars=5)
        self.assertEqual([item.chunk_id for item in first], [item.chunk_id for item in second])


class RetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "test.db"
        initialize_database(self.database_path, PROJECT_ROOT / "data" / "sample" / "adcs.csv")
        documents = build_retrieval_documents(self.database_path)
        chunks = chunk_documents(documents)
        persist_retrieval_corpus(self.database_path, documents, chunks)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_profile_is_retrievable_by_alias(self) -> None:
        results = HybridRetriever(self.database_path).sparse_search(
            "T-DXd 的载荷和 DAR", top_k=3
        )
        self.assertEqual(results[0].retrieval_document_id, "adc_profile:adc_001")

    def test_explicit_pmid_is_resolved_exactly(self) -> None:
        document = RetrievalDocument(
            retrieval_document_id="pubmed:34413126",
            source_type="pubmed",
            source_record_id="34413126",
            title="Dato-DXd preclinical activity",
            content="PMID 34413126 Dato-DXd internalization and DXd release.",
            source_url="https://pubmed.ncbi.nlm.nih.gov/34413126/",
            metadata={},
        )
        persist_retrieval_corpus(
            self.database_path,
            [document],
            chunk_documents([document]),
        )

        results = HybridRetriever(self.database_path).identifier_search(
            "PMID 34413126 的直接摘要证据是什么？",
            source_type="pubmed",
            top_k=5,
        )

        self.assertEqual([item.source_record_id for item in results], ["34413126"])
        self.assertEqual(results[0].retrieval_document_id, "pubmed:34413126")

    def test_persist_is_idempotent(self) -> None:
        documents = build_retrieval_documents(self.database_path)
        chunks = chunk_documents(documents)
        persist_retrieval_corpus(self.database_path, documents, chunks)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM retrieval_documents").fetchone()[0],
                10,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM text_chunks_fts").fetchone()[0],
                len(chunks),
            )

    def test_document_level_ndcg_cannot_exceed_one(self) -> None:
        metrics = _question_metrics(["doc:1", "doc:2"], {"doc:1"}, 10)
        self.assertLessEqual(metrics["ndcg"], 1.0)

    def test_question_review_status_is_propagated(self) -> None:
        reviewed = [{"review_status": "expert_reviewed"} for _ in range(2)]
        mixed = [
            {"review_status": "expert_reviewed"},
            {"review_status": "draft_domain_review"},
        ]
        self.assertEqual(_aggregate_review_status(reviewed), "expert_reviewed")
        self.assertEqual(_aggregate_review_status(mixed), "mixed")


if __name__ == "__main__":
    unittest.main()
