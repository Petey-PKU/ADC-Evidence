from __future__ import annotations

import json
import unittest
from pathlib import Path

from adc_evidence.evaluation.paper_readiness import (
    database_quality_provenance_check,
    public_dataset_audit_check,
)
from adc_evidence.repository import data_quality_metrics


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QualityReportTests(unittest.TestCase):
    def test_public_audit_reports_are_validated_but_partial_data_stays_warning(self) -> None:
        from tests.support import WorkspaceTemporaryDirectory

        with WorkspaceTemporaryDirectory() as directory:
            dataset_path = Path(directory) / "dataset-audit.json"
            dataset_path.write_text(
                json.dumps(
                    {
                        "schema_version": "public-adc-dataset-audit-v1",
                        "database_sha256": "sha256:" + "a" * 64,
                        "counts": {"adcs": 23, "trials": 2, "documents": 3, "entity_links": 4},
                        "source_coverage": {
                            "clinicaltrials": {"coverage_state": "partial"},
                            "pubmed": {"coverage_state": "unknown"},
                        },
                        "status": "partial",
                    }
                ),
                encoding="utf-8",
            )
            catalog_path = Path(directory) / "catalog-audit.json"
            catalog_path.write_text(
                json.dumps(
                    {
                        "schema_version": "public-adc-source-content-audit-v1",
                        "catalog_row_count": 23,
                        "core_fact_candidate_locator_count": 158,
                        "review_status": "triage_only_pending_human_source_locator_review",
                        "ai_or_automatic_labels_are_gold": False,
                    }
                ),
                encoding="utf-8",
            )
            status, detail = public_dataset_audit_check(dataset_path, catalog_path)
        self.assertEqual(status, "warning")
        self.assertIn("status=partial", detail)
        self.assertIn("review_status=triage_only_pending_human_source_locator_review", detail)

    def test_public_audit_rejects_malformed_report(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported schema_version"):
            from tests.support import WorkspaceTemporaryDirectory

            with WorkspaceTemporaryDirectory() as directory:
                path = Path(directory) / "audit.json"
                path.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")
                public_dataset_audit_check(path, None)

    def test_missing_runtime_database_is_explicit_warning(self) -> None:
        status, detail = database_quality_provenance_check(
            PROJECT_ROOT / "path-that-is-not-a-checkout"
        )
        self.assertEqual(status, "warning")
        self.assertIn("deferred", detail)

    def test_committed_quality_report_matches_committed_database(self) -> None:
        report_path = PROJECT_ROOT / "data" / "processed" / "data_quality_report.json"
        database_path = PROJECT_ROOT / "data" / "processed" / "adc_evidence.db"
        if not database_path.exists():
            self.skipTest("demo database is generated or mounted outside a clean checkout")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["report_scope"], "current_committed_demo_seed")
        self.assertEqual(report["database_metrics"], data_quality_metrics(database_path))


if __name__ == "__main__":
    unittest.main()
