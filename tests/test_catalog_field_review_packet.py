from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from scripts.build_catalog_field_review_packet import KEY_FIELDS, build_packet
from tests.support import WorkspaceTemporaryDirectory


class CatalogFieldReviewPacketTests(unittest.TestCase):
    def test_packet_covers_every_key_field_and_leaves_verdict_blank(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog = Path(temporary.name) / "catalog.csv"
            fields = ["adc_id", "adc_name", "source_url", *KEY_FIELDS]
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "adc_id": "adc_001",
                    "adc_name": "Example ADC",
                    "source_url": "https://example.test/source",
                    "target": "HER2",
                    "dar": "",
                })
            packet, manifest = build_packet(catalog)
        finally:
            temporary.cleanup()
        self.assertEqual(len(packet), len(KEY_FIELDS))
        self.assertEqual(manifest["review_item_count"], len(KEY_FIELDS))
        self.assertEqual({item["field"] for item in packet}, set(KEY_FIELDS))
        self.assertTrue(all(item["verification"]["status"] == "pending_primary_check" for item in packet))
        self.assertTrue(all(item["verification"]["verdict"] is None for item in packet))
        dar_item = next(item for item in packet if item["field"] == "dar")
        self.assertEqual(dar_item["value_status"], "missing")
        self.assertEqual(manifest["status"], "awaiting_independent_primary_source_review")

    def test_packet_binds_field_locator_candidates_without_verdicts(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            catalog = root / "catalog.csv"
            fields = ["adc_id", "adc_name", "source_url", *KEY_FIELDS]
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"adc_id": "adc_x", "adc_name": "Example ADC", "source_url": "https://example.test/source"})
            candidates = root / "candidates.jsonl"
            candidates.write_text(json.dumps({
                "adc_id": "adc_x", "field": "target", "candidate_value": "HER2",
                "source_url": "https://example.test/label.pdf", "source_locator": "Section 11",
                "source_tier": "regulator_label", "support_status": "candidate_direct",
                "review_status": "pending_independent_primary_source_review",
            }) + "\n", encoding="utf-8")
            packet, manifest = build_packet(catalog, candidates)
        finally:
            temporary.cleanup()
        target = next(item for item in packet if item["field"] == "target")
        self.assertEqual(target["candidate_source"]["field_locator_candidates"][0]["candidate_value"], "HER2")
        self.assertIsNone(target["verification"]["verdict"])
        self.assertEqual(manifest["candidate_locator_count"], 1)

    def test_packet_does_not_attach_default_public_hints_to_unrelated_catalog(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog = Path(temporary.name) / "catalog.csv"
            fields = ["adc_id", "adc_name", "source_url", *KEY_FIELDS]
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"adc_id": "adc_001", "adc_name": "Fixture", "source_url": "https://example.test/source"})
            packet, manifest = build_packet(catalog)
        finally:
            temporary.cleanup()
        self.assertEqual(manifest["candidate_locator_count"], 0)
        self.assertTrue(all(not item["candidate_source"]["field_locator_candidates"] for item in packet))

    def test_packet_preserves_competing_candidate_values(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            catalog = root / "catalog.csv"
            fields = ["adc_id", "adc_name", "source_url", *KEY_FIELDS]
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"adc_id": "adc_x", "adc_name": "Fixture", "source_url": "https://example.test/source"})
            candidates = root / "candidates.jsonl"
            candidates.write_text("\n".join(json.dumps({
                "adc_id": "adc_x", "field": "dar", "candidate_value": value,
                "source_url": f"https://example.test/{value}", "source_locator": "Results",
                "source_tier": "peer_reviewed_publication", "support_status": "candidate_direct",
                "review_status": "pending_independent_primary_source_review",
            }) for value in ("5.7", "6")) + "\n", encoding="utf-8")
            packet, manifest = build_packet(catalog, candidates)
        finally:
            temporary.cleanup()
        dar = next(item for item in packet if item["field"] == "dar")
        self.assertEqual([hint["candidate_value"] for hint in dar["candidate_source"]["field_locator_candidates"]], ["5.7", "6"])
        self.assertEqual(manifest["candidate_locator_count"], 2)

    def test_packet_rejects_candidate_file_that_does_not_match_catalog(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            root = Path(temporary.name)
            catalog = root / "catalog.csv"
            fields = ["adc_id", "adc_name", "source_url", *KEY_FIELDS]
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"adc_id": "adc_x", "adc_name": "Fixture", "source_url": "https://example.test/source"})
            candidates = root / "candidates.jsonl"
            candidates.write_text(json.dumps({
                "adc_id": "adc_other", "field": "target", "candidate_value": "HER2",
                "source_url": "https://example.test/label.pdf", "source_locator": "Section 11",
            }) + "\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                build_packet(catalog, candidates)
        finally:
            temporary.cleanup()

    def test_packet_rejects_explicit_missing_candidate_file(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog = Path(temporary.name) / "catalog.csv"
            fields = ["adc_id", "adc_name", "source_url", *KEY_FIELDS]
            with catalog.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({"adc_id": "adc_x", "adc_name": "Fixture", "source_url": "https://example.test/source"})
            with self.assertRaises(FileNotFoundError):
                build_packet(catalog, Path(temporary.name) / "missing.jsonl")
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
