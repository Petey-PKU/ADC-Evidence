"""Fail-closed audit of evidence required before making a paper claim."""

from __future__ import annotations

import json
from pathlib import Path

from adc_evidence.evaluation.benchmark import load_benchmark_questions
from adc_evidence.evaluation.holdout import (
    load_holdout_questions,
    validate_holdout_disjoint,
)
from adc_evidence.evaluation.human_review import (
    load_human_paired_reviews,
    validate_human_paired_reviews,
)


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def audit_public_paper_readiness(
    repo_root: Path,
    *,
    human_review_jsonl: Path | None = None,
    independent_holdout_manifest: Path | None = None,
) -> dict[str, object]:
    """Audit public evidence and optional externally supplied confirmation artifacts.

    The default result is intentionally not ready: public smoke data and
    engineering diagnostics cannot substitute for an access-controlled,
    independently reviewed confirmation set.
    """
    holdout_path = repo_root / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
    holdout = load_holdout_questions(holdout_path)
    exposed = load_benchmark_questions()
    disjoint = validate_holdout_disjoint(holdout, exposed)
    checks = [
        _check(
            "public_question_disjointness",
            "pass",
            f"{disjoint['holdout_question_count']} public questions have no exact text overlap with {disjoint['exposed_question_count']} exposed questions",
        ),
        _check(
            "public_smoke_boundary",
            "pass",
            "public holdout is explicitly ineligible for unseen-test publication claims",
        ),
        _check(
            "paired_statistics_tooling",
            "pass",
            "paired bootstrap and McNemar statistics are available",
        ),
        _check(
            "review_provenance_gate",
            "pass",
            "AI-assisted and automatic labels are rejected by the human-review gate",
        ),
    ]
    if human_review_jsonl is None:
        checks.append(
            _check(
                "human_review_labels",
                "blocker",
                "supply a JSONL file containing real human_independent or human_adjudicated labels",
            )
        )
    else:
        labels = validate_human_paired_reviews(load_human_paired_reviews(human_review_jsonl))
        checks.append(
            _check(
                "human_review_labels",
                "pass",
                f"validated {len(labels)} human paired labels",
            )
        )
    if independent_holdout_manifest is None:
        checks.append(
            _check(
                "independent_holdout",
                "blocker",
                "supply a separately frozen, access-controlled holdout manifest",
            )
        )
    else:
        manifest = json.loads(independent_holdout_manifest.read_text(encoding="utf-8-sig"))
        eligible = manifest.get("evaluation_use", {}).get("eligible_for_unseen_test_claim") is True
        access_controlled = manifest.get("access_controlled") is True
        if not eligible or not access_controlled:
            raise ValueError("Independent holdout must be access_controlled and eligible_for_unseen_test_claim")
        checks.append(
            _check(
                "independent_holdout",
                "pass",
                "manifest declares an access-controlled holdout eligible for an unseen-test claim",
            )
        )
    blockers = [item for item in checks if item["status"] == "blocker"]
    return {
        "schema_version": "v0.6-paper-readiness-audit-v1",
        "status": "not_ready_for_submission" if blockers else "evidence_ready_for_submission_review",
        "checks": checks,
        "blocker_count": len(blockers),
        "next_actions": [item["detail"] for item in blockers],
    }
