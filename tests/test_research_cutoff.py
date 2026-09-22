from __future__ import annotations

import json
import unittest
from pathlib import Path


class ResearchCutoffConfigTests(unittest.TestCase):
    def test_cutoff_config_locks_scope_fields_conflicts_and_date_policy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        config = json.loads(
            (root / "configs" / "research_cutoff_2026-09-18.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(config["cutoff_date"], "2026-09-18")
        self.assertEqual(config["primary_scope"]["targets"], ["HER2", "TROP2"])
        self.assertEqual(len(config["adc_fields"]), 10)
        self.assertEqual(len(config["trial_fields"]), 8)
        self.assertEqual(len(config["publication_fields"]), 4)
        self.assertEqual(len(config["known_conflicts_requiring_adjudication"]), 3)
        self.assertIn("historical_freeze", config["date_boundary_policy"])
        self.assertEqual(
            config["current_audit_input"]["interpretation"],
            "diagnostic date audit only; not a historical database freeze",
        )


if __name__ == "__main__":
    unittest.main()
