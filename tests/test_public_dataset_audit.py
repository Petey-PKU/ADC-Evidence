from __future__ import annotations

import sqlite3
import unittest
import datetime as dt
from pathlib import Path

from scripts.audit_public_dataset import audit_database
from tests.support import WorkspaceTemporaryDirectory


class PublicDatasetAuditTests(unittest.TestCase):
    def test_audit_reports_alias_date_and_url_validation_states(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            database = Path(temporary.name) / "snapshot.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE adcs (adc_id TEXT PRIMARY KEY);
                    CREATE TABLE trials (nct_id TEXT PRIMARY KEY, source_url TEXT, last_update_date TEXT);
                    CREATE TABLE documents (document_id TEXT PRIMARY KEY, source_url TEXT, publication_date TEXT);
                    CREATE TABLE entity_links (
                        entity_type TEXT, entity_id TEXT, source_record_type TEXT,
                        source_record_id TEXT, matched_alias TEXT, match_method TEXT
                    );
                    CREATE TABLE entity_aliases (
                        entity_type TEXT, entity_id TEXT, canonical_name TEXT,
                        alias TEXT, normalized_alias TEXT, source TEXT
                    );
                    CREATE TABLE ingestion_source_runs (
                        source TEXT, status TEXT, expected_count INTEGER,
                        collected_count INTEGER, is_complete INTEGER, details_json TEXT
                    );
                    INSERT INTO adcs VALUES ('adc_001');
                    INSERT INTO trials VALUES ('NCT000001','https://clinicaltrials.gov/study/NCT000001','2026-09-11');
                    INSERT INTO documents VALUES ('doc_001','http://pubmed.example/doc','2026-Oct');
                    INSERT INTO entity_links VALUES ('adc','adc_001','trial','NCT000001','known alias','normalized_alias');
                    INSERT INTO entity_links VALUES ('adc','adc_001','document','doc_001','unknown alias','normalized_alias');
                    INSERT INTO entity_aliases VALUES ('adc','adc_001','Fixture','known alias','known alias','seed');
                    INSERT INTO ingestion_source_runs VALUES ('pubmed','partial',2,1,0,'{}');
                    """
                )
            report = audit_database(database, as_of=dt.date(2026, 9, 30))
        finally:
            temporary.cleanup()
        self.assertEqual(report["entity_link_integrity"]["unmatched_alias_count"], 1)
        self.assertEqual(report["entity_link_integrity"]["alias_validation_status"], "needs_review")
        self.assertEqual(report["record_date_quality"]["documents.publication_date"]["after_as_of_count"], 1)
        self.assertEqual(report["record_date_quality"]["documents.publication_date"]["status"], "needs_review")
        self.assertEqual(report["source_url_quality"]["documents"]["status"], "needs_review")
        self.assertEqual(report["source_url_quality"]["trials"]["status"], "pass")

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
                        source_record_type TEXT, source_record_id TEXT,
                        match_method TEXT
                    );
                    CREATE TABLE facts (
                        fact_id TEXT PRIMARY KEY, predicate TEXT,
                        subject_type TEXT, valid_to TEXT
                    );
                    CREATE TABLE fact_evidence (
                        fact_id TEXT, source TEXT, source_url TEXT,
                        is_current INTEGER, valid_to TEXT
                    );
                    CREATE TABLE ingestion_source_runs (
                        source TEXT, status TEXT, expected_count INTEGER,
                        collected_count INTEGER, is_complete INTEGER,
                        details_json TEXT
                    );
                    INSERT INTO adcs VALUES ('adc_001');
                    INSERT INTO trials VALUES ('NCT000001');
                    INSERT INTO documents VALUES ('doc_001');
                    INSERT INTO entity_links VALUES ('adc','adc_001','trial','NCT000001','normalized_alias');
                    INSERT INTO entity_links VALUES ('adc','adc_001','document','doc_001','normalized_alias');
                    INSERT INTO facts VALUES ('fact_1','adc.target','adc',NULL);
                    INSERT INTO fact_evidence VALUES
                      ('fact_1','curated_seed','https://example.test/source',1,NULL);
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
        self.assertEqual(report["link_coverage_by_adc"]["adc_001"], {"trial_record_count": 1, "document_record_count": 1})
        self.assertEqual(report["zero_link_adc_ids"], [])
        self.assertEqual(report["missing_trial_link_adc_ids"], [])
        self.assertEqual(report["missing_document_link_adc_ids"], [])
        self.assertEqual(report["orphan_link_counts"], {"trial": 0, "document": 0})
        self.assertEqual(report["match_method_counts"], {"document:normalized_alias": 1, "trial:normalized_alias": 1})
        self.assertEqual(report["adc_fact_coverage"]["adc.target"], 1)
        self.assertEqual(report["adc_fact_provenance"]["adc.target"]["with_source_url_count"], 1)
        self.assertEqual(report["adc_fact_provenance"]["adc.target"]["source_types"], ["curated_seed"])
        self.assertEqual(report["adc_fact_source_quality_status"], "needs_review")
        self.assertEqual(report["adc_fact_source_quality_reasons"], ["curated_seed_not_independently_reviewed"])
        self.assertEqual(report["adc_fact_source_quality"]["adc.target"], {"missing_url_count": 0, "generic_url_count": 0})
        self.assertEqual(report["incomplete_sources"], ["pubmed"])
        self.assertEqual(report["partial_sources"], ["pubmed"])
        self.assertEqual(report["unknown_sources"], [])
        self.assertEqual(report["source_coverage"]["pubmed"]["coverage_state"], "partial")
        self.assertEqual(report["source_coverage"]["pubmed"]["coverage_ratio"], 0.5)

    def test_audit_keeps_unknown_coverage_separate_from_zero(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            database = Path(temporary.name) / "snapshot.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE adcs (adc_id TEXT PRIMARY KEY);
                    CREATE TABLE trials (nct_id TEXT PRIMARY KEY);
                    CREATE TABLE documents (document_id TEXT PRIMARY KEY);
                    CREATE TABLE entity_links (entity_type TEXT, entity_id TEXT, source_record_type TEXT, source_record_id TEXT, match_method TEXT);
                    CREATE TABLE ingestion_source_runs (
                        source TEXT, status TEXT, expected_count INTEGER,
                        collected_count INTEGER, is_complete INTEGER, details_json TEXT
                    );
                    INSERT INTO adcs VALUES ('adc_001');
                    INSERT INTO ingestion_source_runs VALUES ('adcdb','skipped',NULL,NULL,0,'{"reason":"not configured"}');
                    """
                )
            report = audit_database(database)
        finally:
            temporary.cleanup()
        self.assertEqual(report["source_coverage"]["adcdb"]["coverage_state"], "unknown")
        self.assertIsNone(report["source_coverage"]["adcdb"]["coverage_ratio"])
        self.assertEqual(report["source_coverage"]["adcdb"]["coverage_ratio_reason"], "expected_count_missing_or_nonpositive")
        self.assertEqual(report["unknown_sources"], ["adcdb"])

    def test_audit_flags_generic_current_field_source_urls(self) -> None:
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
                        source_record_type TEXT, source_record_id TEXT,
                        match_method TEXT
                    );
                    CREATE TABLE facts (fact_id TEXT PRIMARY KEY, predicate TEXT, subject_type TEXT, valid_to TEXT);
                    CREATE TABLE fact_evidence (fact_id TEXT, source TEXT, source_url TEXT, is_current INTEGER, valid_to TEXT);
                    CREATE TABLE ingestion_source_runs (source TEXT, status TEXT, expected_count INTEGER, collected_count INTEGER, is_complete INTEGER, details_json TEXT);
                    INSERT INTO adcs VALUES ('adc_001');
                    INSERT INTO facts VALUES ('fact_1','adc.target','adc',NULL);
                    INSERT INTO fact_evidence VALUES ('fact_1','curated_seed','https://www.nmpa.gov.cn/',1,NULL);
                    """
                )
            report = audit_database(database)
        finally:
            temporary.cleanup()
        self.assertEqual(report["adc_fact_source_quality_status"], "needs_review")
        self.assertEqual(report["adc_fact_source_quality_reasons"], ["curated_seed_not_independently_reviewed", "missing_or_generic_url"])
        self.assertEqual(report["adc_fact_source_quality"]["adc.target"]["generic_url_count"], 1)

    def test_audit_uses_latest_timestamped_run_for_incomplete_status(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            database = Path(temporary.name) / "snapshot.db"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE adcs (adc_id TEXT PRIMARY KEY);
                    CREATE TABLE trials (nct_id TEXT PRIMARY KEY);
                    CREATE TABLE documents (document_id TEXT PRIMARY KEY);
                    CREATE TABLE entity_links (entity_type TEXT, entity_id TEXT, source_record_type TEXT, source_record_id TEXT, match_method TEXT);
                    CREATE TABLE ingestion_source_runs (
                        run_id TEXT, source TEXT, started_at TEXT, finished_at TEXT,
                        status TEXT, expected_count INTEGER, collected_count INTEGER,
                        is_complete INTEGER, details_json TEXT
                    );
                    INSERT INTO adcs VALUES ('adc_001');
                    INSERT INTO ingestion_source_runs VALUES
                      ('old','pubmed','2026-01-01','2026-01-01','partial',10,2,0,'{"planned_truncation":true}');
                    INSERT INTO ingestion_source_runs VALUES
                      ('new','pubmed','2026-01-02','2026-01-02','complete',10,10,1,'{"total_count":10}');
                    """
                )
            report = audit_database(database)
        finally:
            temporary.cleanup()
        self.assertEqual(report["source_run_history_count"], 2)
        self.assertEqual(report["latest_source_runs"]["pubmed"]["run_id"], "new")
        self.assertEqual(report["incomplete_sources"], [])


if __name__ == "__main__":
    unittest.main()
