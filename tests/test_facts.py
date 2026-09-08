from __future__ import annotations

import hashlib
import tempfile
import unittest
from argparse import Namespace
from contextlib import closing
from pathlib import Path

from adc_evidence.config import DEFAULT_SEED_PATH
from adc_evidence.database import (
    SCHEMA_VERSION,
    connect,
    create_database,
    initialize_database,
)
from adc_evidence.facts import (
    FactObservationSet,
    ObservedFactValue,
    list_change_events,
    list_current_facts,
    record_fact_sets,
    stable_snapshot_id,
    verify_source_snapshots,
)
from adc_evidence.ingestion.pipeline import run_pipeline
from adc_evidence.records import SourceRecord
from adc_evidence.repository import upsert_source_records


class TemporalFactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "facts.db"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _snapshot(
        self,
        *,
        source: str,
        source_record_id: str,
        content: bytes,
        observed_at: str,
        filename: str,
    ) -> tuple[SourceRecord, str]:
        raw_path = self.root / filename
        raw_path.write_bytes(content)
        checksum = hashlib.sha256(content).hexdigest()
        record = SourceRecord(
            source=source,
            source_record_id=source_record_id,
            retrieved_at=observed_at,
            source_url=f"https://example.test/{source_record_id}",
            raw_path=str(raw_path),
            sha256=checksum,
            dataset_version="test-v1",
        )
        upsert_source_records(
            self.database,
            [record],
            parser_version="test-parser-v1",
        )
        return record, stable_snapshot_id(source, source_record_id, checksum)

    @staticmethod
    def _observation(
        *,
        predicate: str,
        value: object | None,
        source: str,
        source_record_id: str,
        observed_at: str,
        snapshot_id: str | None,
    ) -> FactObservationSet:
        values = (
            [
                ObservedFactValue(
                    value=value,
                    source_locator=predicate,
                )
            ]
            if value is not None
            else []
        )
        return FactObservationSet(
            subject_type="adc" if predicate.startswith("adc.") else "trial",
            subject_id=(
                "adc_001"
                if predicate.startswith("adc.")
                else source_record_id
            ),
            predicate=predicate,
            values=values,
            source=source,
            source_record_id=source_record_id,
            observed_at=observed_at,
            source_url=f"https://example.test/{source_record_id}",
            snapshot_id=snapshot_id,
            extractor="test_v1",
        )

    def test_existing_database_migrates_without_losing_records(self) -> None:
        initialize_database(self.database, DEFAULT_SEED_PATH)
        with closing(connect(self.database)) as connection, connection:
            for table in (
                "change_events",
                "fact_evidence",
                "facts",
                "source_snapshots",
                "schema_versions",
            ):
                connection.execute(f"DROP TABLE {table}")

        create_database(self.database)

        with closing(connect(self.database)) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            adc_count = connection.execute(
                "SELECT COUNT(*) FROM adcs"
            ).fetchone()[0]
            versions = {
                str(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_versions"
                )
            }
        self.assertEqual(adc_count, 10)
        self.assertTrue(
            {
                "source_snapshots",
                "facts",
                "fact_evidence",
                "change_events",
            }.issubset(tables)
        )
        self.assertIn(SCHEMA_VERSION, versions)

    def test_source_snapshots_are_immutable_idempotent_and_verifiable(self) -> None:
        record, snapshot_id = self._snapshot(
            source="adcdb",
            source_record_id="DRG000001",
            content=b"first immutable source body",
            observed_at="2026-08-21T00:00:00+00:00",
            filename="adcdb.html",
        )
        repeated = record.model_copy(
            update={"retrieved_at": "2026-08-22T00:00:00+00:00"}
        )
        upsert_source_records(
            self.database,
            [repeated],
            parser_version="test-parser-v1",
        )

        with closing(connect(self.database)) as connection:
            snapshot_count = connection.execute(
                "SELECT COUNT(*) FROM source_snapshots"
            ).fetchone()[0]
            current_retrieved_at = connection.execute(
                """
                SELECT retrieved_at
                FROM source_records
                WHERE source = 'adcdb' AND source_record_id = 'DRG000001'
                """
            ).fetchone()[0]
        self.assertEqual(snapshot_count, 1)
        self.assertEqual(
            current_retrieved_at,
            "2026-08-22T00:00:00+00:00",
        )
        self.assertEqual(
            verify_source_snapshots(self.database)[0]["status"],
            "valid",
        )
        self.assertEqual(
            verify_source_snapshots(self.database)[0]["snapshot_id"],
            snapshot_id,
        )

        Path(record.raw_path).write_bytes(b"tampered")
        self.assertEqual(
            verify_source_snapshots(self.database)[0]["status"],
            "hash_mismatch",
        )

    def test_same_source_update_creates_history_and_change_event(self) -> None:
        _, first_snapshot = self._snapshot(
            source="adcdb",
            source_record_id="DRG000001",
            content=b'{"dar": 8.0}',
            observed_at="2026-08-21T00:00:00+00:00",
            filename="adcdb-v1.json",
        )
        first = self._observation(
            predicate="adc.dar",
            value=8.0,
            source="adcdb",
            source_record_id="DRG000001",
            observed_at="2026-08-21T00:00:00+00:00",
            snapshot_id=first_snapshot,
        )
        initial = record_fact_sets(self.database, [first])
        repeated = record_fact_sets(self.database, [first])
        self.assertEqual(initial["facts_created"], 1)
        self.assertEqual(repeated["idempotent_groups"], 1)

        _, second_snapshot = self._snapshot(
            source="adcdb",
            source_record_id="DRG000001",
            content=b'{"dar": 7.6}',
            observed_at="2026-08-22T00:00:00+00:00",
            filename="adcdb-v2.json",
        )
        second = self._observation(
            predicate="adc.dar",
            value=7.6,
            source="adcdb",
            source_record_id="DRG000001",
            observed_at="2026-08-22T00:00:00+00:00",
            snapshot_id=second_snapshot,
        )
        changed = record_fact_sets(self.database, [second])

        current = list_current_facts(
            self.database,
            subject_id="adc_001",
            predicate="adc.dar",
        )
        events = list_change_events(self.database)
        with closing(connect(self.database)) as connection:
            historical = connection.execute(
                """
                SELECT status, valid_to
                FROM facts
                WHERE predicate = 'adc.dar' AND display_value = '8.0'
                """
            ).fetchone()
        self.assertEqual(changed["changes_created"], 1)
        self.assertEqual([item["value"] for item in current], [7.6])
        self.assertEqual(historical["status"], "superseded")
        self.assertEqual(
            historical["valid_to"],
            "2026-08-22T00:00:00+00:00",
        )
        self.assertEqual(events[0]["event_type"], "adc.structure.changed")
        self.assertEqual(events[0]["old_value"], [8.0])
        self.assertEqual(events[0]["new_value"], [7.6])

    def test_cross_source_conflict_is_preserved_and_can_resolve(self) -> None:
        _, snapshot_id = self._snapshot(
            source="adcdb",
            source_record_id="DRG000001",
            content=b'{"dar": 8.0}',
            observed_at="2026-08-21T00:00:00+00:00",
            filename="adcdb.json",
        )
        adcdb = self._observation(
            predicate="adc.dar",
            value=8.0,
            source="adcdb",
            source_record_id="DRG000001",
            observed_at="2026-08-21T00:00:00+00:00",
            snapshot_id=snapshot_id,
        )
        seed_old = self._observation(
            predicate="adc.dar",
            value=7.6,
            source="curated_seed",
            source_record_id="adc_001",
            observed_at="2026-08-21T00:01:00+00:00",
            snapshot_id=None,
        )
        record_fact_sets(self.database, [adcdb])
        record_fact_sets(self.database, [seed_old])

        conflicted = list_current_facts(
            self.database,
            subject_id="adc_001",
            predicate="adc.dar",
        )
        self.assertEqual(
            {item["value"] for item in conflicted},
            {7.6, 8.0},
        )
        self.assertEqual(
            {item["status"] for item in conflicted},
            {"conflicted"},
        )
        self.assertIn(
            "fact.conflict_detected",
            {
                event["event_type"]
                for event in list_change_events(self.database)
            },
        )

        seed_new = self._observation(
            predicate="adc.dar",
            value=8.0,
            source="curated_seed",
            source_record_id="adc_001",
            observed_at="2026-08-22T00:00:00+00:00",
            snapshot_id=None,
        )
        record_fact_sets(self.database, [seed_new])

        resolved = list_current_facts(
            self.database,
            subject_id="adc_001",
            predicate="adc.dar",
        )
        event_types = {
            event["event_type"]
            for event in list_change_events(self.database)
        }
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["value"], 8.0)
        self.assertEqual(
            set(resolved[0]["sources"]),
            {"adcdb", "curated_seed"},
        )
        self.assertIn("fact.conflict_resolved", event_types)

    def test_empty_observation_supersedes_removed_field_value(self) -> None:
        _, first_snapshot = self._snapshot(
            source="clinicaltrials",
            source_record_id="NCT00000001",
            content=b'{"phases": ["PHASE2"]}',
            observed_at="2026-08-21T00:00:00+00:00",
            filename="trial-v1.json",
        )
        record_fact_sets(
            self.database,
            [
                self._observation(
                    predicate="trial.phases",
                    value="PHASE2",
                    source="clinicaltrials",
                    source_record_id="NCT00000001",
                    observed_at="2026-08-21T00:00:00+00:00",
                    snapshot_id=first_snapshot,
                )
            ],
        )
        _, second_snapshot = self._snapshot(
            source="clinicaltrials",
            source_record_id="NCT00000001",
            content=b'{"phases": []}',
            observed_at="2026-08-22T00:00:00+00:00",
            filename="trial-v2.json",
        )
        record_fact_sets(
            self.database,
            [
                self._observation(
                    predicate="trial.phases",
                    value=None,
                    source="clinicaltrials",
                    source_record_id="NCT00000001",
                    observed_at="2026-08-22T00:00:00+00:00",
                    snapshot_id=second_snapshot,
                )
            ],
        )

        self.assertEqual(
            list_current_facts(
                self.database,
                subject_id="NCT00000001",
                predicate="trial.phases",
            ),
            [],
        )
        events = list_change_events(
            self.database,
            event_type="trial.phases.changed",
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["old_value"], ["PHASE2"])
        self.assertEqual(events[0]["new_value"], [])

    def test_offline_pipeline_populates_seed_facts(self) -> None:
        summary = run_pipeline(
            Namespace(
                database=self.database,
                raw_root=self.root / "raw",
                quality_report=self.root / "quality.json",
                pubmed_max=10,
                trial_page_size=10,
                trial_max_pages=1,
                adcdb_limit=10,
                skip_pubmed=True,
                skip_trials=True,
                skip_adcdb=True,
                strict=True,
            )
        )

        current = list_current_facts(
            self.database,
            subject_type="adc",
        )
        self.assertEqual(summary["status"], "complete")
        self.assertGreater(len(current), 50)
        self.assertEqual({item["sources"][0] for item in current}, {"curated_seed"})
        self.assertEqual(
            summary["quality_metrics"]["current_fact_count"],
            len(current),
        )
        with closing(connect(self.database)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )

    def test_fact_batch_rolls_back_when_a_later_snapshot_is_invalid(self) -> None:
        valid = self._observation(
            predicate="adc.dar",
            value=8.0,
            source="curated_seed",
            source_record_id="adc_001",
            observed_at="2026-08-21T00:00:00+00:00",
            snapshot_id=None,
        )
        invalid = self._observation(
            predicate="adc.target",
            value="HER2",
            source="adcdb",
            source_record_id="DRG000001",
            observed_at="2026-08-21T00:00:00+00:00",
            snapshot_id="snap_does_not_exist",
        )

        with self.assertRaisesRegex(ValueError, "Unknown source snapshot"):
            record_fact_sets(self.database, [valid, invalid])

        self.assertEqual(list_current_facts(self.database), [])


if __name__ == "__main__":
    unittest.main()
