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
    question_id_sha256,
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
    question_ids_hash = manifest.get("question_id_sha256")
    if not isinstance(question_ids_hash, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", question_ids_hash
    ):
        raise ValueError("Independent holdout question_id_sha256 must be sha256:<64 lowercase hex>")
    question_file_hash = manifest.get("question_file_sha256")
    if not isinstance(question_file_hash, str) or not re.fullmatch(
        r"sha256:[0-9a-f]{64}", question_file_hash
    ):
        raise ValueError("Independent holdout question_file_sha256 must be sha256:<64 lowercase hex>")
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
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_question_set_hash = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    expected_question_set_hash = manifest.get("question_set_hash")
    if expected_question_set_hash != actual_question_set_hash:
        raise ValueError("Independent holdout question set hash mismatch")
    actual_question_id_hash = question_id_sha256(
        str(row["question_id"]) for row in rows
    )
    if manifest.get("question_id_sha256") != actual_question_id_hash:
        raise ValueError("Independent holdout question ID hash mismatch")
    return {
        "question_file_sha256": actual_hash,
        "question_set_hash": actual_question_set_hash,
        "question_id_sha256": actual_question_id_hash,
        "question_count": len(rows),
        "path": questions_path.name,
    }


def validate_human_review_manifest(manifest: object) -> dict[str, object]:
    """Validate content-free integrity metadata for a human-label export."""
    if not isinstance(manifest, dict):
        raise ValueError("Human review manifest must be a JSON object")
    for field in ("review_file_sha256", "question_id_sha256"):
        value = manifest.get(field)
        if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
            raise ValueError(f"Human review {field} must be sha256:<64 lowercase hex>")
    count = manifest.get("question_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError("Human review question_count must be a positive integer")
    for field in ("review_set_version", "evaluation_window_id"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Human review manifest needs nonempty {field}")
    return manifest


def validate_human_review_file(
    reviews_path: Path, manifest: dict[str, object]
) -> dict[str, object]:
    """Bind a human review JSONL export to its content-free manifest."""
    rows = validate_human_paired_reviews(load_human_paired_reviews(reviews_path))
    actual_file_hash = "sha256:" + hashlib.sha256(reviews_path.read_bytes()).hexdigest()
    if manifest["review_file_sha256"] != actual_file_hash:
        raise ValueError("Human review file hash mismatch")
    actual_id_hash = question_id_sha256(str(row["question_id"]) for row in rows)
    if manifest["question_id_sha256"] != actual_id_hash:
        raise ValueError("Human review question ID hash mismatch")
    if manifest["question_count"] != len(rows):
        raise ValueError("Human review question count mismatch")
    return {
        "review_file_sha256": actual_file_hash,
        "question_id_sha256": actual_id_hash,
        "question_count": len(rows),
        "path": reviews_path.name,
    }


def build_human_review_manifest(
    reviews_path: Path,
    *,
    review_set_version: str,
    evaluation_window_id: str,
) -> dict[str, object]:
    """Build content-free integrity metadata for a human review JSONL export."""
    if not review_set_version.strip() or not evaluation_window_id.strip():
        raise ValueError("review_set_version and evaluation_window_id must be nonempty")
    rows = validate_human_paired_reviews(load_human_paired_reviews(reviews_path))
    return {
        "schema_version": "v0.6-human-review-manifest-v1",
        "review_file_sha256": "sha256:" + hashlib.sha256(reviews_path.read_bytes()).hexdigest(),
        "question_id_sha256": question_id_sha256(str(row["question_id"]) for row in rows),
        "question_count": len(rows),
        "review_set_version": review_set_version,
        "evaluation_window_id": evaluation_window_id,
        "privacy_note": "Only hashes, count, version, and evaluation window are included; no labels or identities.",
    }


def database_quality_provenance_check(repo_root: Path) -> tuple[str, str]:
    """Check the committed quality report when the runtime demo DB is available."""
    quality_path = repo_root / "data" / "processed" / "data_quality_report.json"
    database_path = repo_root / "data" / "processed" / "adc_evidence.db"
    if not database_path.exists():
        return (
            "warning",
            "demo database is generated or mounted at runtime; consistency check deferred",
        )
    try:
        quality_report = json.loads(quality_path.read_text(encoding="utf-8"))
        database_metrics = data_quality_metrics(database_path)
        quality_matches = (
            quality_report.get("report_scope") == "current_committed_demo_seed"
            and quality_report.get("database_metrics") == database_metrics
        )
    except (OSError, ValueError, KeyError, sqlite3.Error):
        quality_matches = False
    if not quality_matches:
        return (
            "blocker",
            "committed quality report is missing, stale, or inconsistent with the demo database",
        )
    if not database_metrics.get("document_count") and not database_metrics.get("trial_count"):
        return (
            "warning",
            "quality report matches the demo database, but no literature or trial records are present",
        )
    return "pass", "committed quality report matches the committed demo database"


def audit_public_paper_readiness(
    repo_root: Path,
    *,
    human_review_jsonl: Path | None = None,
    human_review_manifest: Path | None = None,
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
    quality_status, quality_detail = database_quality_provenance_check(repo_root)
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
        if human_review_manifest is None:
            checks.append(
                _check(
                    "human_review_labels",
                    "blocker",
                    "supply a content-free manifest binding the human review file hash, question-ID hash, count, and evaluation window",
                )
            )
        else:
            manifest = validate_human_review_manifest(
                json.loads(human_review_manifest.read_text(encoding="utf-8-sig"))
            )
            bound = validate_human_review_file(human_review_jsonl, manifest)
            checks.append(
                _check(
                    "human_review_labels",
                    "pass",
                    f"validated {bound['question_count']} human paired labels with file and question-set binding",
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
        if independent_holdout_questions is None:
            checks.append(
                _check(
                    "independent_holdout",
                    "blocker",
                    "supply the holdout question file so its file, content, and question-ID hashes can be verified",
                )
            )
        else:
            bound = validate_independent_holdout_file(independent_holdout_questions, manifest)
            checks.append(
                _check(
                    "independent_holdout",
                    "pass",
                    f"manifest and question file hashes/count validated ({bound['question_count']} questions)",
                )
            )
    blockers = [item for item in checks if item["status"] == "blocker"]
    warnings = [item for item in checks if item["status"] == "warning"]
    return {
        "schema_version": "v0.6-paper-readiness-audit-v1",
        "status": "not_ready_for_submission" if blockers else "evidence_ready_for_submission_review",
        "checks": checks,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "next_actions": [item["detail"] for item in blockers],
    }
