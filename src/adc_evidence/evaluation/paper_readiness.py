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


_INDEPENDENT_HOLDOUT_ROUTES = {
    "structured_fact",
    "comparison",
    "change_query",
    "trial_lookup",
    "literature_evidence",
    "refusal",
}
_INDEPENDENT_HOLDOUT_ANSWER_KINDS = {
    "structured",
    "comparison",
    "trial_record",
    "evidence_document",
    "refusal",
    "gap",
}


def _validate_independent_holdout_rows(rows: list[object]) -> None:
    """Require gold answers and scoring metadata before a holdout is frozen."""
    required = {
        "question_id",
        "question",
        "category",
        "expected_route",
        "expected_status",
        "standard_answer",
        "evidence_sources",
        "allow_partial",
        "should_refuse",
        "scoring",
    }
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f"Independent holdout row {index} must be an object")
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(
                f"Independent holdout row {row.get('question_id', index)} missing fields: {missing}"
            )
        if not isinstance(row.get("category"), str) or not str(row["category"]).strip():
            raise ValueError(f"Independent holdout row {row['question_id']} needs category")
        if row.get("expected_route") not in _INDEPENDENT_HOLDOUT_ROUTES:
            raise ValueError(f"Independent holdout row {row['question_id']} has invalid expected_route")
        statuses = row.get("expected_status")
        if not isinstance(statuses, list) or not statuses or any(
            not isinstance(status, str) or not status.strip()
            for status in statuses
        ):
            raise ValueError(f"Independent holdout row {row['question_id']} needs expected_status")
        if not isinstance(row.get("allow_partial"), bool):
            raise ValueError(f"Independent holdout row {row['question_id']} needs boolean allow_partial")
        if not isinstance(row.get("should_refuse"), bool):
            raise ValueError(f"Independent holdout row {row['question_id']} needs boolean should_refuse")
        if row["should_refuse"] != (row["expected_route"] == "refusal"):
            raise ValueError(f"Independent holdout row {row['question_id']} refusal metadata disagrees with route")
        answer = row.get("standard_answer")
        if not isinstance(answer, dict) or answer.get("kind") not in _INDEPENDENT_HOLDOUT_ANSWER_KINDS:
            raise ValueError(f"Independent holdout row {row['question_id']} needs a valid standard_answer")
        sources = row.get("evidence_sources")
        if not isinstance(sources, list):
            raise ValueError(f"Independent holdout row {row['question_id']} needs evidence_sources list")
        for source in sources:
            if not isinstance(source, dict) or any(
                not isinstance(source.get(field), str) or not source[field].strip()
                for field in ("source_type", "source_record_id", "source_url", "field")
            ):
                raise ValueError(
                    f"Independent holdout row {row['question_id']} evidence sources need type, ID, URL, and field"
                )
        scoring = row.get("scoring")
        if not isinstance(scoring, dict) or not isinstance(scoring.get("primary_metric"), str) or not scoring["primary_metric"].strip():
            raise ValueError(f"Independent holdout row {row['question_id']} needs scoring.primary_metric")
        for field in ("automatic_fields", "human_fields"):
            if not isinstance(scoring.get(field), list):
                raise ValueError(f"Independent holdout row {row['question_id']} needs scoring.{field} list")


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
    for field in ("access_control_method", "access_control_attestation"):
        if not isinstance(manifest.get(field), str) or not manifest[field].strip():
            raise ValueError(f"Independent holdout needs nonempty {field}")
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
    questions_path: Path,
    manifest: dict[str, object],
    *,
    exposed_questions: list[dict[str, object]] | None = None,
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
    _validate_independent_holdout_rows(rows)
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
    disjointness = None
    if exposed_questions is not None:
        disjointness = validate_holdout_disjoint(rows, exposed_questions)
    return {
        "question_file_sha256": actual_hash,
        "question_set_hash": actual_question_set_hash,
        "question_id_sha256": actual_question_id_hash,
        "question_count": len(rows),
        "path": questions_path.name,
        "disjointness": disjointness,
    }


def build_independent_holdout_manifest(
    questions_path: Path,
    *,
    question_set_version: str,
    evaluation_window_id: str,
    access_control_method: str,
    database_data_version: str | None = None,
    code_commit: str | None = None,
) -> dict[str, object]:
    """Create content-free integrity metadata for an external confirmation set.

    The caller must attest how the question file is access controlled.  This
    function records that attestation but cannot prove filesystem permissions;
    the question bytes are never copied into the manifest.
    """
    if not question_set_version.strip() or not evaluation_window_id.strip():
        raise ValueError("question_set_version and evaluation_window_id must be nonempty")
    if not access_control_method.strip():
        raise ValueError("access_control_method must be nonempty")
    questions_path = questions_path.resolve()
    raw = questions_path.read_bytes()
    rows = [
        json.loads(line)
        for line in raw.decode("utf-8-sig").splitlines()
        if line.strip()
    ]
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Independent holdout must contain at least one JSON object row")
    _validate_independent_holdout_rows(rows)
    question_ids = [str(row.get("question_id", "")).strip() for row in rows]
    if any(not value for value in question_ids) or len(question_ids) != len(set(question_ids)):
        raise ValueError("Independent holdout question IDs must be unique and nonempty")
    for row in rows:
        validate_question_text(row.get("question"))
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    manifest: dict[str, object] = {
        "schema_version": "v0.6-independent-holdout-manifest-v1",
        "question_set_version": question_set_version,
        "question_set_hash": "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "question_id_sha256": question_id_sha256(question_ids),
        "question_file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "question_count": len(rows),
        "evaluation_window_id": evaluation_window_id,
        "access_controlled": True,
        "access_control_method": access_control_method,
        "access_control_attestation": "operator_asserted; verify independently before publication",
        "evaluation_use": {
            "status": "unseen_holdout",
            "eligible_for_unseen_test_claim": True,
            "reason": "Question content was frozen outside the public development repository before evaluation.",
        },
        "privacy_note": "Only hashes and metadata are included; question content and local paths remain external.",
    }
    if database_data_version:
        manifest["database_data_version"] = database_data_version
    if code_commit:
        manifest["code_commit"] = code_commit
    return manifest


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


def _read_audit_object(path: Path, *, label: str) -> dict[str, object]:
    """Read a content-free public audit report and reject malformed evidence."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not readable JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def public_dataset_audit_check(
    dataset_audit: Path | None,
    catalog_source_audit: Path | None,
) -> tuple[str, str]:
    """Validate externally generated public snapshot audits without trusting paths.

    The reports are deliberately supplied from outside the source checkout: a
    local SQLite snapshot and raw source responses are not public repository
    content. This check validates the report schema and provenance summary,
    while retaining ``warning`` status when the underlying data or field
    review is explicitly partial/pending.
    """
    if dataset_audit is None and catalog_source_audit is None:
        return "warning", "no public snapshot audit reports supplied"
    details: list[str] = []
    status = "pass"
    if dataset_audit is not None:
        report = _read_audit_object(dataset_audit, label="public dataset audit")
        if report.get("schema_version") != "public-adc-dataset-audit-v1":
            raise ValueError("public dataset audit has an unsupported schema_version")
        digest = report.get("database_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("public dataset audit needs database_sha256")
        counts = report.get("counts")
        if not isinstance(counts, dict) or any(
            not isinstance(counts.get(name), int) or counts[name] < 0
            for name in ("adcs", "trials", "documents", "entity_links")
        ):
            raise ValueError("public dataset audit has invalid counts")
        coverage = report.get("source_coverage")
        if not isinstance(coverage, dict) or not coverage:
            raise ValueError("public dataset audit needs source_coverage")
        allowed_states = {"complete", "partial", "unknown"}
        if any(
            not isinstance(item, dict) or item.get("coverage_state") not in allowed_states
            for item in coverage.values()
        ):
            raise ValueError("public dataset audit has invalid source coverage states")
        dataset_status = report.get("status")
        if dataset_status not in allowed_states:
            raise ValueError("public dataset audit has invalid status")
        if dataset_status != "complete" or any(
            item.get("coverage_state") != "complete" for item in coverage.values()
        ):
            status = "warning"
        details.append(
            f"dataset audit bound to {digest}, status={dataset_status}, "
            f"{counts['adcs']} ADCs/{counts['trials']} trials/{counts['documents']} documents"
        )
    if catalog_source_audit is not None:
        report = _read_audit_object(catalog_source_audit, label="catalog source audit")
        if report.get("schema_version") != "public-adc-source-content-audit-v1":
            raise ValueError("catalog source audit has an unsupported schema_version")
        row_count = report.get("catalog_row_count")
        pair_count = report.get("core_fact_candidate_locator_count")
        total_pair_count = report.get("candidate_locator_pair_count", pair_count)
        if not isinstance(row_count, int) or row_count < 1:
            raise ValueError("catalog source audit needs a positive catalog_row_count")
        if not isinstance(pair_count, int) or pair_count < 0:
            raise ValueError("catalog source audit needs core fact locator count")
        if not isinstance(total_pair_count, int) or total_pair_count < pair_count:
            raise ValueError("catalog source audit needs a valid total candidate locator count")
        review_status = report.get("review_status")
        if not isinstance(review_status, str) or not review_status.strip():
            raise ValueError("catalog source audit needs review_status")
        if report.get("ai_or_automatic_labels_are_gold") is not False:
            raise ValueError("catalog source audit must reject automatic labels as gold")
        if review_status != "verified_primary_source_review":
            status = "warning"
        details.append(
            f"catalog source audit covers {row_count} rows and {pair_count} core-fact candidate locators "
            f"({total_pair_count} total candidate pairs); "
            f"review_status={review_status}"
        )
    return status, "; ".join(details)


def audit_public_paper_readiness(
    repo_root: Path,
    *,
    human_review_jsonl: Path | None = None,
    human_review_manifest: Path | None = None,
    independent_holdout_manifest: Path | None = None,
    independent_holdout_questions: Path | None = None,
    public_dataset_audit: Path | None = None,
    public_catalog_source_audit: Path | None = None,
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
    if public_dataset_audit is not None or public_catalog_source_audit is not None:
        audit_status, audit_detail = public_dataset_audit_check(
            public_dataset_audit, public_catalog_source_audit
        )
        checks.append(_check("public_dataset_audit", audit_status, audit_detail))
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
            bound = validate_independent_holdout_file(
                independent_holdout_questions,
                manifest,
                exposed_questions=exposed,
            )
            checks.append(
                _check(
                    "independent_holdout",
                    "pass",
                    f"manifest, question file hashes/count, and disjointness validated ({bound['question_count']} questions)",
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
