from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from adc_evidence.database import initialize_database
from adc_evidence.records import TrialRecord
from adc_evidence.repository import upsert_trials
from scripts.relink_public_snapshot import relink_snapshot
from tests.support import WorkspaceTemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"


class PublicSnapshotRelinkTests(unittest.TestCase):
    def test_relink_uses_catalog_alias_without_network(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary:
            database = Path(temporary) / "snapshot.db"
            initialize_database(database, CATALOG)
            upsert_trials(database, [
                TrialRecord(
                    nct_id="NCT06968585",
                    brief_title="A Study of A166 versus T-DM1",
                    source_url="https://clinicaltrials.gov/study/NCT06968585",
                    raw_path="raw/trial.json",
                    checksum="trial-checksum",
                )
            ])
            summary = relink_snapshot(database, CATALOG)
            with sqlite3.connect(database) as connection:
                row = connection.execute(
                    "SELECT entity_id, matched_alias FROM entity_links "
                    "WHERE source_record_type='trial' AND source_record_id=?",
                    ("NCT06968585",),
                ).fetchall()
        self.assertGreaterEqual(summary["trial_link_count"], 1)
        self.assertIn(("adc_017", "a166"), row)


if __name__ == "__main__":
    unittest.main()
