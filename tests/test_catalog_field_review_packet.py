from __future__ import annotations

import csv
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


if __name__ == "__main__":
    unittest.main()
