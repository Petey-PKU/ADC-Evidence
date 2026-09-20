from __future__ import annotations

import csv
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts.audit_public_catalog import audit_catalog
from scripts.audit_public_catalog_sources import audit_catalog_sources, source_class
from tests.support import WorkspaceTemporaryDirectory


class PublicCatalogAuditTests(unittest.TestCase):
    def test_source_content_audit_is_triage_only_and_flags_structural_gaps(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            path = Path(temporary.name) / "catalog.csv"
            path.write_text(
                "adc_id,adc_name,aliases,source_url\n"
                "adc_001,Example ADC,ExADC,https://www.fda.gov/example\n",
                encoding="utf-8",
            )
            with patch(
                "scripts.audit_public_catalog_sources._fetch",
                return_value=(200, "text/html", "FDA approves Example ADC for cancer"),
            ):
                report = audit_catalog_sources(path)
        finally:
            temporary.cleanup()
        self.assertEqual(source_class("https://www.fda.gov/example"), "regulator_fda")
        self.assertEqual(report["name_or_alias_match_count"], 1)
        self.assertEqual(report["field_level_source_missing_count"], 7)
        self.assertEqual(report["core_fact_field_level_source_missing_count"], 8)
        self.assertEqual(report["review_status"], "triage_only_pending_human_source_locator_review")
        self.assertFalse(report["ai_or_automatic_labels_are_gold"])
        record = report["records"][0]
        self.assertEqual(record["inspection_status"], "text_scanned")
        self.assertEqual(record["field_assessment"]["dar"], "field_level_source_missing")
        self.assertEqual(record["field_assessment"]["approval_date"], "candidate_support_only")

    def test_source_content_audit_distinguishes_candidate_locators_from_missing_ones(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog = Path(temporary.name) / "catalog.csv"
            catalog.write_text(
                "adc_id,adc_name,aliases,source_url\n"
                "adc_001,Example ADC,ExADC,https://www.fda.gov/example\n",
                encoding="utf-8",
            )
            locators = Path(temporary.name) / "locators.jsonl"
            locators.write_text(
                json.dumps({
                    "adc_id": "adc_001", "field": "target", "candidate_value": "Example ADC",
                    "source_url": "https://www.fda.gov/example",
                }) + "\n",
                encoding="utf-8",
            )
            with patch(
                "scripts.audit_public_catalog_sources._fetch",
                return_value=(200, "text/html", "FDA approves Example ADC for cancer"),
            ):
                report = audit_catalog_sources(catalog, candidate_locators=locators)
        finally:
            temporary.cleanup()
        self.assertEqual(report["structural_field_pair_count"], 7)
        self.assertEqual(report["structural_field_candidate_locator_count"], 1)
        self.assertEqual(report["structural_field_candidate_locator_missing_count"], 6)
        self.assertEqual(report["structural_field_candidate_locator_coverage_ratio"], 0.1429)
        self.assertEqual(report["core_fact_pair_count"], 8)
        self.assertEqual(report["core_fact_candidate_locator_count"], 1)
        self.assertEqual(report["core_fact_candidate_locator_missing_count"], 7)
        self.assertEqual(report["core_fact_candidate_locator_coverage_ratio"], 0.125)
        self.assertEqual(report["candidate_value_match_count"], 1)
        self.assertEqual(report["candidate_value_match_eligible_count"], 1)
        self.assertEqual(report["candidate_value_match_rate"], 1.0)
        self.assertEqual(report["records"][0]["field_assessment"]["target"], "candidate_locator_pending_human_review")
        self.assertEqual(report["records"][0]["field_assessment"]["dar"], "field_level_source_missing")
        self.assertEqual(report["records"][0]["field_assessment"]["indication"], "field_level_source_missing")
    def test_audit_reports_generic_sources_and_pending_primary_checks(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            path = Path(temporary.name) / "catalog.csv"
            fields = [
                "adc_id", "adc_name", "aliases", "target", "antibody", "linker_name",
                "linker_type", "payload_name", "payload_class", "dar", "indication", "development_status",
                "company", "source_url", "data_review_status", "brand_name", "approval_date",
                "approval_jurisdictions", "catalog_status", "dar_reported", "as_of_date", "verification_status",
            ]
            row = {field: "value" for field in fields}
            row.update({
                "adc_id": "adc_001", "adc_name": "Example ADC", "source_url": "https://www.nmpa.gov.cn/",
                "approval_date": "2025-01-01", "as_of_date": "2026-06-30",
                "catalog_status": "marketed", "verification_status": "primary_check_pending",
            })
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(row)
            report = audit_catalog(path, requested_as_of="2026-09-30")
        finally:
            temporary.cleanup()
        self.assertEqual(report["row_count"], 1)
        self.assertEqual(report["generic_source_url_count"], 1)
        self.assertEqual(report["source_specificity_counts"]["generic"], 1)
        self.assertEqual(report["field_coverage_counts"]["adc_name"], 1)
        self.assertEqual(report["field_coverage_counts"]["dar"], 1)
        self.assertEqual(report["review_status"], "needs_primary_source_review")
        self.assertEqual(report["manual_review_queue"][0]["adc_id"], "adc_001")

    def test_catalog_hash_is_stable_across_newline_conventions(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            lf = Path(temporary.name) / "catalog-lf.csv"
            crlf = Path(temporary.name) / "catalog-crlf.csv"
            content = "adc_id,adc_name\nadc_001,Example ADC\n"
            lf.write_bytes(content.encode("utf-8"))
            crlf.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))
            # The minimal fixture is intentionally incomplete; the audit still
            # computes provenance before reporting its review queue.
            lf_report = audit_catalog(lf, requested_as_of="2026-09-30")
            crlf_report = audit_catalog(crlf, requested_as_of="2026-09-30")
        finally:
            temporary.cleanup()
        self.assertEqual(lf_report["catalog_sha256"], crlf_report["catalog_sha256"])


if __name__ == "__main__":
    unittest.main()
