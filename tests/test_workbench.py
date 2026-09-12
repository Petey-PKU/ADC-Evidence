from __future__ import annotations
from tests.support import WorkspaceTemporaryDirectory

import csv
import io
import unittest
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.facts import (
    FactObservationSet,
    ObservedFactValue,
    record_fact_sets,
)
from adc_evidence.workbench import (
    ADC_FIELD_SPECS,
    EVIDENCE_BRIEF_SCHEMA_VERSION,
    build_evidence_brief,
    compare_adcs,
    comparison_to_csv,
    comparison_to_markdown,
    evidence_brief_to_json,
    evidence_brief_to_markdown,
    evidence_data_version,
    get_adc_evidence_card,
    list_changes,
    sync_public_seed_facts,
)


class EvidenceWorkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = WorkspaceTemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "adc.db"
        sync_public_seed_facts(
            self.database,
            observed_at="2026-08-01T00:00:00+00:00",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _observation(
        self,
        *,
        adc_id: str,
        predicate: str,
        value: object,
        source: str,
        observed_at: str,
    ) -> FactObservationSet:
        return FactObservationSet(
            subject_type="adc",
            subject_id=adc_id,
            predicate=predicate,
            values=[
                ObservedFactValue(
                    value=value,
                    source_locator=f"fixture.{predicate}",
                    evidence_text=f"{predicate}: {value}",
                )
            ],
            source=source,
            source_record_id=adc_id if source == "curated_seed" else "ADCDB001",
            observed_at=observed_at,
            source_url=f"https://example.test/{source}/{adc_id}",
            extractor="public_test_fixture_v1",
        )

    def test_public_seed_fact_sync_is_idempotent(self) -> None:
        before = evidence_data_version(self.database)
        result = sync_public_seed_facts(
            self.database,
            observed_at="2026-08-21T00:00:00+00:00",
        )
        after = evidence_data_version(self.database)

        self.assertEqual(result["idempotent_groups"], 100)
        self.assertEqual(result["facts_created"], 0)
        self.assertEqual(result["evidence_created"], 0)
        self.assertEqual(before["data_version"], after["data_version"])

    def test_adc_card_traces_every_nonempty_field(self) -> None:
        card = get_adc_evidence_card(
            self.database,
            "adc_001",
            now=datetime(2026, 8, 21, tzinfo=UTC),
        )

        self.assertEqual(card["adc_name"], "Trastuzumab deruxtecan")
        self.assertEqual(len(card["fields"]), len(ADC_FIELD_SPECS))
        self.assertTrue(card["traceability_complete"])
        self.assertEqual(card["conflicted_fields"], [])
        dar = card["field_map"]["adc.dar"]
        self.assertEqual(dar["display_value"], "8.0")
        self.assertEqual(dar["freshness_status"], "demo_source")
        self.assertEqual(dar["evidence_count"], 1)
        evidence = dar["values"][0]["evidence"][0]
        self.assertEqual(evidence["source"], "curated_seed")
        self.assertEqual(evidence["source_record_id"], "adc_001")
        self.assertEqual(evidence["observed_at"], "2026-08-01T00:00:00+00:00")
        self.assertEqual(evidence["review_status"], "needs_review")
        self.assertTrue(evidence["source_url"])

    def test_cross_source_conflict_and_history_are_visible(self) -> None:
        record_fact_sets(
            self.database,
            [
                self._observation(
                    adc_id="adc_001",
                    predicate="adc.dar",
                    value=7.0,
                    source="adcdb",
                    observed_at="2026-08-20T00:00:00+00:00",
                )
            ],
        )
        record_fact_sets(
            self.database,
            [
                self._observation(
                    adc_id="adc_001",
                    predicate="adc.dar",
                    value=6.0,
                    source="adcdb",
                    observed_at="2026-08-21T00:00:00+00:00",
                )
            ],
        )
        card = get_adc_evidence_card(
            self.database,
            "adc_001",
            now=datetime(2026, 8, 21, 1, tzinfo=UTC),
        )
        dar = card["field_map"]["adc.dar"]

        self.assertEqual(dar["status"], "conflicted")
        self.assertEqual(
            {value["value"] for value in dar["values"]},
            {8.0, 6.0},
        )
        self.assertIn("adc.dar", card["conflicted_fields"])
        self.assertIn(7.0, {value["value"] for value in dar["history"]})

    def test_comparison_has_traceable_cells_and_versioned_exports(self) -> None:
        comparison = compare_adcs(
            self.database,
            ["adc_001", "adc_006"],
            now=datetime(2026, 8, 21, tzinfo=UTC),
        )
        self.assertEqual(len(comparison["rows"]), len(ADC_FIELD_SPECS))
        self.assertTrue(comparison["traceability_complete"])
        target_row = next(
            row for row in comparison["rows"] if row["predicate"] == "adc.target"
        )
        self.assertEqual(target_row["cells"]["adc_001"]["display_value"], "HER2")
        self.assertEqual(target_row["cells"]["adc_006"]["display_value"], "TROP2")
        self.assertGreater(
            target_row["cells"]["adc_001"]["evidence_count"],
            0,
        )

        csv_rows = list(
            csv.DictReader(
                io.StringIO(comparison_to_csv(comparison).decode("utf-8-sig"))
            )
        )
        self.assertEqual(len(csv_rows), len(ADC_FIELD_SPECS))
        self.assertTrue(csv_rows[0]["data_version"].startswith("data_"))
        self.assertEqual(csv_rows[0]["policy_version"], "0.6.0")
        markdown = comparison_to_markdown(comparison)
        self.assertIn("## 单元格证据", markdown)
        self.assertIn("https://", markdown)
        with self.assertRaisesRegex(ValueError, "2 to 10"):
            compare_adcs(self.database, ["adc_001"])

    def test_recent_changes_support_all_product_filters(self) -> None:
        record_fact_sets(
            self.database,
            [
                self._observation(
                    adc_id="adc_001",
                    predicate="adc.development_status",
                    value="investigational",
                    source="curated_seed",
                    observed_at="2026-08-21T00:00:00+00:00",
                )
            ],
        )
        current_time = datetime(2026, 8, 21, 12, tzinfo=UTC)
        changes = list_changes(
            self.database,
            days=1,
            adc_ids=["adc_001"],
            targets=["HER2"],
            sources=["curated_seed"],
            event_types=["adc.development_status.changed"],
            now=current_time,
        )

        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["old_value"], ["approved"])
        self.assertEqual(changes[0]["new_value"], ["investigational"])
        self.assertEqual(changes[0]["entities"]["adc_ids"], ["adc_001"])
        self.assertEqual(changes[0]["entities"]["targets"], ["HER2"])
        self.assertEqual(
            list_changes(
                self.database,
                days=1,
                adc_ids=["adc_006"],
                now=current_time,
            ),
            [],
        )
        with self.assertRaisesRegex(ValueError, "1, 7 or 30"):
            list_changes(self.database, days=2, now=current_time)

    def test_evidence_brief_contains_versions_evidence_and_disclaimer(self) -> None:
        brief = build_evidence_brief(
            self.database,
            ["adc_001", "adc_006"],
            generated_at=datetime(2026, 8, 21, tzinfo=UTC),
        )
        self.assertEqual(
            brief["brief_schema_version"],
            EVIDENCE_BRIEF_SCHEMA_VERSION,
        )
        self.assertTrue(brief["data_version"]["data_version"].startswith("data_"))
        self.assertEqual(brief["data_version"]["policy_version"], "0.6.0")
        self.assertGreater(brief["evidence_count"], 0)
        self.assertIn("临床建议", brief["disclaimer"])
        markdown = evidence_brief_to_markdown(brief)
        self.assertIn("字段级证据", markdown)
        self.assertIn("数据版本", markdown)
        self.assertIn("https://", markdown)
        json_export = evidence_brief_to_json(brief)
        self.assertIn(brief["brief_id"].encode("utf-8"), json_export)


if __name__ == "__main__":
    unittest.main()
