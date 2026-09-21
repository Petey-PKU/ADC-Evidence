from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from scripts.build_catalog_field_review_packet import KEY_FIELDS, build_packet
from scripts.validate_catalog_field_review import validate_review_packet
from tests.support import WorkspaceTemporaryDirectory


class CatalogFieldReviewValidationTests(unittest.TestCase):
    def _packet_files(self, directory: Path) -> tuple[Path, Path, Path]:
        catalog = directory / "catalog.csv"
        with catalog.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["adc_id", "adc_name", "source_url", *KEY_FIELDS])
            writer.writeheader()
            writer.writerow({"adc_id": "adc_001", "adc_name": "Example ADC", "source_url": "https://example.test/source"})
        packet, manifest = build_packet(catalog)
        packet_path = directory / "packet.jsonl"
        packet_path.write_text("".join(json.dumps(item) + "\n" for item in packet), encoding="utf-8")
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return catalog, packet_path, manifest_path

    def test_pending_packet_passes_but_is_not_review_ready(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog, packet, manifest = self._packet_files(Path(temporary.name))
            report = validate_review_packet(packet, manifest, catalog_path=catalog)
        finally:
            temporary.cleanup()
        self.assertEqual(report["item_count"], len(KEY_FIELDS))
        self.assertEqual(report["pending_count"], len(KEY_FIELDS))
        self.assertFalse(report["review_ready"])

    def test_completed_item_requires_locator_and_verdict(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            directory = Path(temporary.name)
            catalog, packet, manifest = self._packet_files(directory)
            lines = [json.loads(line) for line in packet.read_text(encoding="utf-8").splitlines()]
            lines[0]["verification"] = {
                "status": "reviewed_primary_source",
                "verdict": "supported",
                "source_locator": "label.pdf#page=2",
                "reviewer_slot": "primary",
                "review_origin": "human_independent",
            }
            packet.write_text("".join(json.dumps(item) + "\n" for item in lines), encoding="utf-8")
            report = validate_review_packet(packet, manifest, catalog_path=catalog)
        finally:
            temporary.cleanup()
        self.assertEqual(report["completed_count"], 1)
        self.assertEqual(report["pending_count"], len(KEY_FIELDS) - 1)

    def test_completed_item_rejects_missing_or_ai_review_metadata(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            directory = Path(temporary.name)
            catalog, packet, manifest = self._packet_files(directory)
            lines = [json.loads(line) for line in packet.read_text(encoding="utf-8").splitlines()]
            lines[0]["verification"] = {
                "status": "reviewed_primary_source",
                "verdict": "supported",
                "source_locator": "label.pdf#page=2",
            }
            packet.write_text("".join(json.dumps(item) + "\n" for item in lines), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_review_packet(packet, manifest, catalog_path=catalog)

            lines[0]["verification"]["reviewer_slot"] = "primary"
            lines[0]["verification"]["review_origin"] = "ai_assisted_primary"
            packet.write_text("".join(json.dumps(item) + "\n" for item in lines), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_review_packet(packet, manifest, catalog_path=catalog)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
