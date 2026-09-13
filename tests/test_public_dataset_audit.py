from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from scripts.audit_public_dataset import audit_database
from tests.support import WorkspaceTemporaryDirectory


class PublicDatasetAuditTests(unittest.TestCase):
    def test_audit_reports_deduplication_links_and_partial_source(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            database = Path(temporary.name) / "snapshot.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE adcs (adc_id TEXT PRIMARY KEY);
                    CREATE TABLE trials (nct_id TEXT PRIMARY KEY);
                    CREATE TABLE documents (document_id TEXT PRIMARY KEY);
                    CREATE TABLE entity_links (
                        entity_type TEXT, entity_id TEXT,
                        source_record_type TEXT, source_record_id TEXT
                    );
                    CREATE TABLE facts (
                        predicate TEXT, subject_type TEXT, valid_to TEXT
                    );
                    CREATE TABLE ingestion_source_runs (
                        source TEXT, status TEXT, expected_count INTEGER,
                        collected_count INTEGER, is_complete INTEGER,
                        details_json TEXT
                    );
                    INSERT INTO adcs VALUES ('adc_001');
                    INSERT INTO trials VALUES ('NCT000001');
                    INSERT INTO documents VALUES ('doc_001');
                    INSERT INTO entity_links VALUES ('adc','adc_001','trial','NCT000001');
                    INSERT INTO entity_links VALUES ('adc','adc_001','document','doc_001');
                    INSERT INTO facts VALUES ('adc.target','adc',NULL);
                    INSERT INTO ingestion_source_runs VALUES
                      ('clinicaltrials','complete',1,1,1,'{"total_count":1}');
                    INSERT INTO ingestion_source_runs VALUES
                      ('pubmed','partial',2,1,0,'{"planned_truncation":true}');
                    """
                )
            report = audit_database(database)
        finally:
            temporary.cleanup()
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["duplicate_identifier_counts"]["trials"], 0)
        self.assertEqual(report["linked_record_counts"], {"trials": 1, "documents": 1})
        self.assertEqual(report["adc_fact_coverage"]["adc.target"], 1)
        self.assertEqual(report["incomplete_sources"], ["pubmed"])


if __name__ == "__main__":
    unittest.main()
