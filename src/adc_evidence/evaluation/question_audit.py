"""Offline question integrity and complete, split-aware system report audit."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.config import (
    FROZEN_BENCHMARK_QUESTIONS_PATH,
    GENERATION_QUESTIONS_PATH,
    RETRIEVAL_QUESTIONS_PATH,
)
from adc_evidence.evaluation.benchmark import (
    automatic_diagnostics,
    load_benchmark_questions,
    question_set_manifest,
    validate_arm_report,
    validate_question_text,
)


def inspect_question_file(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    result: dict[str, object] = {
        "file_name": path.name,
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "hash_representation": "file_bytes",
        "valid": False,
        "row_count": 0,
        "issues": [],
    }
    issues = result["issues"]
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        issues.append({"reason": "invalid_utf8"})
        return result
    if text.startswith("\ufeff"):
        issues.append({"reason": "unexpected_utf8_bom"})
    ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            issues.append({"line": line_number, "reason": "invalid_json"})
            continue
        result["row_count"] += 1
        if not isinstance(row, dict):
            issues.append({"line": line_number, "reason": "row_must_be_object"})
            continue
        question_id = row.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            issues.append({"line": line_number, "reason": "missing_question_id"})
        elif question_id in ids:
            issues.append({"line": line_number, "reason": "duplicate_question_id"})
        else:
            ids.add(question_id)
        try:
            validate_question_text(row.get("question"))
        except ValueError:
            issues.append({"line": line_number, "reason": "invalid_question_text"})
    if not result["row_count"]:
        issues.append({"reason": "empty_file"})
    result["valid"] = not issues
    return result


def audit_system_report(
    report: dict[str, object], questions: list[dict[str, object]]
) -> dict[str, object]:
    """Join all canonical IDs, including legacy IDs prefixed with dev_*."""
    validate_arm_report(report, questions)
    if report["arm"] != "adc_evidence":
        raise ValueError("Route audit requires an adc_evidence system report")
    outputs = report["questions"]
    by_id = {row["question_id"]: row for row in outputs}
    mismatches = []
    by_split = {}
    for split in sorted({row["split"] for row in questions}):
        expected = [row for row in questions if row["split"] == split]
        actual = [by_id[row["question_id"]] for row in expected]
        route_matches = 0
        status_matches = 0
        for question, output in zip(expected, actual):
            route_match = output.get("route") == question["expected_route"]
            status_match = output["status"] in question["expected_status"]
            route_matches += route_match
            status_matches += status_match
            if not route_match or not status_match:
                mismatches.append({
                    "question_id": question["question_id"],
                    "split": split,
                    "category": question["category"],
                    "route_mismatch": not route_match,
                    "status_mismatch": not status_match,
                    "expected_route": question["expected_route"],
                    "actual_route": output.get("route"),
                    "expected_status": question["expected_status"],
                    "actual_status": output["status"],
                })
        by_split[split] = {
            "question_count": len(expected),
            "route_match_count": route_matches,
            "route_mismatch_count": len(expected) - route_matches,
            "route_missing_count": sum(row.get("route") is None for row in actual),
            "route_match_rate": round(route_matches / len(expected), 4),
            "expected_status_match_count": status_matches,
            "status_counts": dict(sorted(Counter(row["status"] for row in actual).items())),
            "error_count": sum(row["status"] == "error" for row in actual),
        }
    diagnostics = automatic_diagnostics(outputs, questions)
    return {
        "run_id": report["run_id"],
        "model": report["model"],
        "evaluated_at": report["evaluated_at"],
        "question_set_hash": report["question_set_hash"],
        "question_count": len(questions),
        "route_mismatch_count": sum(row["route_mismatch"] for row in mismatches),
        "by_split": by_split,
        "recomputed_diagnostics": diagnostics,
        "stored_diagnostics_match": report.get("automatic_diagnostics") == diagnostics,
        "mismatches": mismatches,
        "interpretation": "Development diagnostics only; no semantic correctness or unseen-test claim.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--system-report", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.system_report and args.output.resolve() == args.system_report.resolve():
        parser.error("Audit output must not overwrite the input report")
    files = [
        inspect_question_file(path)
        for path in (
            RETRIEVAL_QUESTIONS_PATH,
            GENERATION_QUESTIONS_PATH,
            FROZEN_BENCHMARK_QUESTIONS_PATH,
        )
    ]
    payload = {
        "schema_version": "question-audit-v1",
        "audited_at": datetime.now(UTC).isoformat(),
        "files": files,
        "encoding_and_rows_valid": all(row["valid"] for row in files),
    }
    if payload["encoding_and_rows_valid"]:
        questions = load_benchmark_questions()
        payload["manifest"] = question_set_manifest(questions)
        if args.system_report:
            raw = args.system_report.read_bytes()
            payload["input_report_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
            payload["system_report_audit"] = audit_system_report(
                json.loads(raw.decode("utf-8")), questions
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Preserve previous audit artifacts; use a new output name for another run.
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    print(json.dumps({
        "encoding_and_rows_valid": payload["encoding_and_rows_valid"],
        "system_report_audited": "system_report_audit" in payload,
    }))
    if not payload["encoding_and_rows_valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
