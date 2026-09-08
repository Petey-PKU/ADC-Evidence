from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from adc_evidence.config import EVIDENCE_POLICY_PATH


class ScopePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[str] = Field(min_length=1)
    supported_jobs: list[str] = Field(min_length=1)
    prohibited_jobs: list[str] = Field(min_length=1)


class SourcePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1)
    cadence: Literal["daily", "weekly", "monthly", "manual"]
    max_age_hours: int | None = Field(default=None, ge=1)
    is_authoritative_external_source: bool

    @model_validator(mode="after")
    def validate_freshness_contract(self) -> "SourcePolicy":
        if self.cadence == "manual" and self.max_age_hours is not None:
            raise ValueError("manual sources must not define max_age_hours")
        if self.cadence != "manual" and self.max_age_hours is None:
            raise ValueError("scheduled sources must define max_age_hours")
        return self


class FieldPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value_type: Literal[
        "string", "text", "enum", "decimal", "integer", "date", "object"
    ]
    cardinality: Literal["one", "many"]
    preferred_sources: list[str] = Field(min_length=1)
    conflict_resolution: Literal[
        "authoritative_first", "require_review", "preserve_all"
    ]
    material_change: bool


class ChangeTypePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["low", "medium", "high", "critical"]
    review_required: bool
    tracked_field: str | None = None


class EvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    scope: ScopePolicy
    sources: dict[str, SourcePolicy] = Field(min_length=1)
    fields: dict[str, FieldPolicy] = Field(min_length=1)
    fact_statuses: list[str] = Field(min_length=1)
    review_statuses: list[str] = Field(min_length=1)
    change_types: dict[str, ChangeTypePolicy] = Field(min_length=1)
    answer_routes: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "EvidencePolicy":
        named_lists = {
            "scope.targets": self.scope.targets,
            "scope.supported_jobs": self.scope.supported_jobs,
            "scope.prohibited_jobs": self.scope.prohibited_jobs,
            "fact_statuses": self.fact_statuses,
            "review_statuses": self.review_statuses,
            "answer_routes": self.answer_routes,
        }
        for list_name, values in named_lists.items():
            if len(values) != len(set(values)):
                raise ValueError(f"{list_name} must not contain duplicates")

        overlapping_jobs = set(self.scope.supported_jobs) & set(
            self.scope.prohibited_jobs
        )
        if overlapping_jobs:
            raise ValueError(
                "supported_jobs and prohibited_jobs overlap: "
                + ", ".join(sorted(overlapping_jobs))
            )

        source_names = set(self.sources)
        for field_name, field_policy in self.fields.items():
            unknown_sources = set(field_policy.preferred_sources) - source_names
            if unknown_sources:
                raise ValueError(
                    f"{field_name} references unknown sources: "
                    f"{', '.join(sorted(unknown_sources))}"
                )
            if field_policy.conflict_resolution == "authoritative_first":
                first_source = self.sources[field_policy.preferred_sources[0]]
                if not first_source.is_authoritative_external_source:
                    raise ValueError(
                        f"{field_name} uses authoritative_first with a "
                        "non-authoritative first source"
                    )

        for change_name, change_policy in self.change_types.items():
            if (
                change_policy.tracked_field is not None
                and change_policy.tracked_field not in self.fields
            ):
                raise ValueError(
                    f"{change_name} references unknown field: "
                    f"{change_policy.tracked_field}"
                )

        required_fact_statuses = {"current", "superseded", "conflicted"}
        missing_fact_statuses = required_fact_statuses - set(self.fact_statuses)
        if missing_fact_statuses:
            raise ValueError(
                "missing required fact statuses: "
                + ", ".join(sorted(missing_fact_statuses))
            )

        required_review_statuses = {
            "needs_review",
            "reviewed_supported",
            "reviewed_unsupported",
            "reviewed_conflicted",
            "superseded",
        }
        missing_review_statuses = required_review_statuses - set(
            self.review_statuses
        )
        if missing_review_statuses:
            raise ValueError(
                "missing required review statuses: "
                + ", ".join(sorted(missing_review_statuses))
            )

        required_answer_routes = {
            "structured_fact",
            "comparison",
            "change_query",
            "trial_lookup",
            "literature_evidence",
            "refusal",
        }
        missing_answer_routes = required_answer_routes - set(self.answer_routes)
        if missing_answer_routes:
            raise ValueError(
                "missing required answer routes: "
                + ", ".join(sorted(missing_answer_routes))
            )
        return self


def load_evidence_policy(path: Path = EVIDENCE_POLICY_PATH) -> EvidencePolicy:
    """Load and validate the versioned evidence policy."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvidencePolicy.model_validate(payload)
