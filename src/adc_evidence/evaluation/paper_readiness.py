"""Fail-closed audit of evidence required before making a paper claim."""

from __future__ import annotations

import json
import hashlib
import re
import sqlite3
from pathlib import Path

from adc_evidence.evaluation.benchmark import load_benchmark_questions
from adc_evidence.evaluation.benchmark import validate_question_text
from adc_evidence.evaluation.holdout import (
    load_holdout_questions,
    validate_holdout_disjoint,
)
from adc_evidence.evaluation.human_review import (
    load_human_paired_reviews,
    validate_human_paired_reviews,
)
from adc_evidence.evaluation.public_hygiene import scan_tracked_public_files
from adc_evidence.repository import data_quality_metrics


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def validate_independent_holdout_manifest(manifest: object) -> dict[str, object]:
    """Validate the minimum integrity metadata for a confirmation holdout."""
    if not isinstance(manifest, dict):
        raise ValueError("Independent holdout manifest must be a JSON object")
    evaluation_use = manifest.get("evaluation_use")
    if not isinstance(evaluation_use, dict):
        raise ValueError("Independent holdout manifest needs evaluation_use metadata")
    if evaluation_use.get("eligible_for_unseen_test_claim") is not True:
        raise ValueError("Independent holdout must be eligible_for_unseen_test_claim")
    if evaluation_use.get("status") != "unseen_holdout":
        raise ValueError("Independent holdout must have status=unseen_holdout")
    if manifest.get("access_controlled") is not True:
        raise ValueError("Independent holdout must be access_controlled")
    question_count = manifest.get("question_count")
    if not isinstance(question_count, int) or isinstance(question_count, bool) or question_count < 1:
        raise ValueError("Independent holdout question_count must be a positive integer")
    question_set_hash = manifest.get("question_set_hash")
    if not isinstance(question_set_hash, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", question_set_hash
    ):
        raise ValueError("Independent holdout question_set_hash must be sha256:<64 lowercase hex>")
    for field in ("question_set_version", "evaluation_window_id"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Independent holdout needs nonempty {field}")
    return manifest


def validate_independent_holdout_file(
    questions_path: Path, manifest: dict[str, object]
) -> dict[str, object]:
    """Bind an external JSONL question file to its manifest without exposing rows."""
    raw = questions_path.read_bytes()
    expected_hash = manifest.get("question_file_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", expected_hash
    ):
        raise ValueError("Independent holdout needs question_file_sha256 for file binding")
    actual_hash = "sha256:" + hashlib.sha256(raw).hexdigest()
    if actual_hash != expected_hash:
        raise ValueError("Independent holdout question file hash mismatch")
    rows = [
        json.loads(line)
        for line in raw.decode("utf-8-sig").splitlines()
        if line.strip()
    ]
    if len(rows) != manifest["question_count"]:
        raise ValueError("Independent holdout question file count mismatch")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Independent holdout question file rows must be objects")
    question_ids = [str(row.get("question_id", "")) for row in rows]
    if any(not question_id.strip() for question_id in question_ids):
        raise ValueError("Independent holdout question IDs must be nonempty")
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Independent holdout question IDs must be unique")
    for row in rows:
        try:
            validate_question_text(row.get("question"))
        except ValueError as exc:
            raise ValueError("Independent holdout contains invalid question text") from exc
    return {
        "question_file_sha256": actual_hash,
        "question_count": len(rows),
        "path": questions_path.name,
    }


def audit_public_paper_readiness(
    repo_root: Path,
    *,
    human_review_jsonl: Path | None = None,
    independent_holdout_manifest: Path | None = None,
    independent_holdout_questions: Path | None = None,
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
            "paired bootstrap, exact McNemar, and Holm adjustment tools are available",
        ),
        _check(
            "review_provenance_gate",
            "pass",
            "AI-assisted and automatic labels are rejected by the human-review gate",
        ),
    ]
    hygiene = scan_tracked_public_files(repo_root)
    hygiene_findings = hygiene.get("findings", [])
    hygiene_finding_count = len(hygiene_findings) if isinstance(hygiene_findings, list) else 0
    checks.append(
        _check(
            "public_repository_hygiene",
            "pass" if hygiene["status"] == "clean" else "blocker",
            (
                f"scanned {hygiene['scanned_file_count']} tracked files with no secret/path findings"
                if hygiene["status"] == "clean"
                else f"found {hygiene_finding_count} secret/path hygiene findings"
            ),
        )
    )
    quality_path = repo_root / "data" / "processed" / "data_quality_report.json"
    database_path = repo_root / "data" / "processed" / "adc_evidence.db"
    if not database_path.exists():
        quality_status = "warning"
        quality_detail = "demo database is generated or mounted at runtime; consistency check deferred"
    else:
        try:
            quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
            quality_matches = (
                quality_report.get("report_scope") == "current_committed_demo_seed"
                and quality_report.get("database_metrics") == data_quality_metrics(database_path)
            )
        except (OSError, ValueError, KeyError, sqlite3.Error):
            quality_matches = False
        quality_status = "pass" if quality_matches else "blocker"
        quality_detail = (
            "committed quality report matches the committed demo database"
            if quality_matches
            else "committed quality report is missing, stale, or inconsistent with the demo database"
        )
    checks.append(
        _check(
            "database_quality_provenance",
            quality_status,
            quality_detail,
        )
    )
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
        manifest = validate_independent_holdout_manifest(
            json.loads(independent_holdout_manifest.read_text(encoding="utf-8-sig"))
        )
        binding_detail = "manifest declares an access-controlled holdout eligible for an unseen-test claim"
        if independent_holdout_questions is not None:
            bound = validate_independent_holdout_file(independent_holdout_questions, manifest)
            binding_detail = (
                f"manifest and question file hash/count validated ({bound['question_count']} questions)"
            )
        checks.append(
            _check(
                "independent_holdout",
                "pass",
                binding_detail,
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
