from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from scripts.validate_public_catalog_scope import validate_catalog_scope
from tests.support import WorkspaceTemporaryDirectory


class PublicCatalogScopeTests(unittest.TestCase):
    def test_current_scope_policy_covers_catalog_and_separates_extended_modalities(self) -> None:
        root = Path(__file__).resolve().parents[1]
        report = validate_catalog_scope(
            root / "data/public/marketed_adc_catalog.csv",
            root / "data/public/catalog_scope_policy.json",
        )
        self.assertEqual(report["catalog_row_count"], 23)
        self.assertEqual(report["core_row_count"], 21)
        self.assertEqual(report["extended_row_count"], 2)
        self.assertEqual(report["class_counts"]["photoimmunoconjugate"], 1)
        self.assertEqual(report["class_counts"]["recombinant_immunotoxin"], 1)
        self.assertEqual(report["catalog_status_counts"], {"marketed": 22, "withdrawn": 1})
        self.assertEqual(
            report["catalog_status_by_scope"],
            {"core:marketed": 21, "extended:marketed": 1, "extended:withdrawn": 1},
        )
        self.assertEqual(report["excluded_record_ids"], ["adc_021", "adc_023"])

    def test_scope_policy_rejects_mismatched_catalog_id(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            catalog = root / "catalog.csv"
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["adc_id", "catalog_status"])
                writer.writeheader()
                writer.writerow({"adc_id": "adc_001", "catalog_status": "marketed"})
            policy = root / "policy.json"
            policy.write_text(json.dumps({
                "schema_version": "public-adc-catalog-scope-v1",
                "classes": {"antibody_drug_conjugate": {"included_in_core": True, "definition": "x"}},
                "records": {"adc_002": "antibody_drug_conjugate"},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "IDs differ"):
                validate_catalog_scope(catalog, policy)
        finally:
            temporary.cleanup()
