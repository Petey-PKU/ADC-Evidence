from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path

from scripts.build_catalog_field_review_packet import KEY_FIELDS, build_packet
from scripts.merge_catalog_field_reviews import merge_catalog_field_reviews
from tests.support import WorkspaceTemporaryDirectory


class CatalogFieldReviewMergeTests(unittest.TestCase):
    def _files(self, directory: Path) -> tuple[Path, Path, Path, list[dict[str, object]]]:
        catalog = directory / "catalog.csv"
        with catalog.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["adc_id", "adc_name", "source_url", *KEY_FIELDS])
            writer.writeheader()
            writer.writerow({"adc_id": "adc_001", "adc_name": "Example ADC", "source_url": "https://example.test/source"})
        packet, manifest = build_packet(catalog)
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return catalog, manifest_path, directory, packet

    @staticmethod
    def _write(path: Path, rows: list[dict[str, object]]) -> None:
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    def _completed(self, packet: list[dict[str, object]], slot: str, origin: str) -> list[dict[str, object]]:
        rows = json.loads(json.dumps(packet))
        for row in rows:
            row["verification"] = {
                "status": "reviewed_primary_source",
                "reviewer_slot": slot,
                "review_origin": origin,
                "verdict": "supported",
                "confirmed_value": row["candidate_value"] or None,
                "source_locator": "label.pdf#page=2",
                "notes": None,
            }
        return rows

    def test_matching_independent_packets_are_ready(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog, manifest, directory, packet = self._files(Path(temporary.name))
            primary_rows = self._completed(packet, "primary", "human_independent")
            secondary_rows = self._completed(packet, "secondary", "human_independent")
            primary = directory / "primary.jsonl"
            secondary = directory / "secondary.jsonl"
            self._write(primary, primary_rows)
            self._write(secondary, secondary_rows)
            report = merge_catalog_field_reviews(primary, secondary, manifest, catalog)
        finally:
            temporary.cleanup()
        self.assertEqual(report["item_count"], len(KEY_FIELDS))
        self.assertEqual(report["disagreement_count"], 0)
        self.assertTrue(report["review_ready"])
        self.assertEqual(report["status"], "ready_for_catalog_update")

    def test_disagreement_requires_adjudication(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog, manifest, directory, packet = self._files(Path(temporary.name))
            primary_rows = self._completed(packet, "primary", "human_independent")
            secondary_rows = self._completed(packet, "secondary", "human_independent")
            secondary_rows[0]["verification"]["verdict"] = "unclear"
            primary = directory / "primary.jsonl"
            secondary = directory / "secondary.jsonl"
            adjudicator = directory / "adjudicator.jsonl"
            self._write(primary, primary_rows)
            self._write(secondary, secondary_rows)
            report = merge_catalog_field_reviews(primary, secondary, manifest, catalog)
            self.assertFalse(report["review_ready"])
            self.assertEqual(report["status"], "needs_adjudication")

            adjudicator_rows = self._completed(packet, "adjudicator", "human_adjudicated")
            for row in adjudicator_rows:
                row["verification"]["status"] = "adjudicated"
            self._write(adjudicator, adjudicator_rows)
            report = merge_catalog_field_reviews(primary, secondary, manifest, catalog, adjudicator_packet=adjudicator)
        finally:
            temporary.cleanup()
        self.assertTrue(report["review_ready"])
        self.assertEqual(report["adjudicated_disagreement_count"], 1)

    def test_ai_assisted_packet_is_rejected(self) -> None:
        temporary = WorkspaceTemporaryDirectory()
        try:
            catalog, manifest, directory, packet = self._files(Path(temporary.name))
            primary_rows = self._completed(packet, "primary", "ai_assisted_primary")
            secondary_rows = self._completed(packet, "secondary", "human_independent")
            primary = directory / "primary.jsonl"
            secondary = directory / "secondary.jsonl"
            self._write(primary, primary_rows)
            self._write(secondary, secondary_rows)
            with self.assertRaises(ValueError):
                merge_catalog_field_reviews(primary, secondary, manifest, catalog)
        finally:
            temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
