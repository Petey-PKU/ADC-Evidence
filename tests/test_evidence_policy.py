from __future__ import annotations

import copy
import unittest

from pydantic import ValidationError

from adc_evidence.evidence_policy import EvidencePolicy, load_evidence_policy


class EvidencePolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_evidence_policy()

    def test_default_policy_loads_and_covers_v06_scope(self) -> None:
        self.assertEqual(self.policy.policy_version, "0.6.0")
        self.assertEqual(set(self.policy.scope.targets), {"HER2", "TROP2"})
        self.assertIn("adc.development_status", self.policy.fields)
        self.assertIn("trial.overall_status", self.policy.fields)
        self.assertIn("publication.abstract", self.policy.fields)
        self.assertIn("change_query", self.policy.answer_routes)

    def test_scheduled_sources_have_freshness_limits(self) -> None:
        for source_name, source in self.policy.sources.items():
            with self.subTest(source=source_name):
                if source.cadence == "manual":
                    self.assertIsNone(source.max_age_hours)
                else:
                    self.assertIsNotNone(source.max_age_hours)

    def test_unknown_source_reference_is_rejected(self) -> None:
        payload = self.policy.model_dump(mode="json")
        payload["fields"]["adc.target"]["preferred_sources"] = [
            "unknown-source"
        ]
        with self.assertRaises(ValidationError):
            EvidencePolicy.model_validate(payload)

    def test_unknown_change_field_is_rejected(self) -> None:
        payload = self.policy.model_dump(mode="json")
        payload["change_types"]["trial.overall_status.changed"][
            "tracked_field"
        ] = "trial.not_a_field"
        with self.assertRaises(ValidationError):
            EvidencePolicy.model_validate(payload)

    def test_authoritative_first_requires_an_external_authority(self) -> None:
        payload = self.policy.model_dump(mode="json")
        payload["fields"]["trial.overall_status"]["preferred_sources"] = [
            "curated_seed"
        ]
        with self.assertRaises(ValidationError):
            EvidencePolicy.model_validate(payload)

    def test_required_review_status_cannot_be_removed(self) -> None:
        payload = copy.deepcopy(self.policy.model_dump(mode="json"))
        payload["review_statuses"].remove("reviewed_conflicted")
        with self.assertRaises(ValidationError):
            EvidencePolicy.model_validate(payload)

    def test_required_answer_route_cannot_be_removed(self) -> None:
        payload = self.policy.model_dump(mode="json")
        payload["answer_routes"].remove("change_query")
        with self.assertRaises(ValidationError):
            EvidencePolicy.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
