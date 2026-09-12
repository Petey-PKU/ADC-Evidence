"""Same-corpus comparison utilities for the deterministic offline baseline."""
from __future__ import annotations

from collections import Counter
from typing import Any

from adc_evidence.evaluation.benchmark import (
    OFFLINE_BASELINE_VERSION,
    IMPLEMENTATION_VERSION,
    validate_arm_report,
)


def compare_offline_reports(
    system_report: dict[str, Any],
    baseline_report: dict[str, Any],
    questions: list[dict[str, object]],
) -> dict[str, object]:
    """Summarize paired engineering diagnostics without semantic scoring."""
    validate_arm_report(system_report, questions)
    validate_arm_report(baseline_report, questions)
    if system_report["arm"] != "adc_evidence":
        raise ValueError("system_report must be the adc_evidence arm")
    if baseline_report["arm"] != "offline_rag_baseline":
        raise ValueError("baseline_report must be the offline_rag_baseline arm")
    for key in ("question_set_hash", "evaluation_window_id", "prompt_version"):
        if system_report.get(key) != baseline_report.get(key):
            raise ValueError(f"Offline reports disagree on {key}")
    expected = {str(row["question_id"]): row for row in questions}
    system = {str(row["question_id"]): row for row in system_report["questions"]}
    baseline = {str(row["question_id"]): row for row in baseline_report["questions"]}
    paired_status = Counter()
    paired_routes = Counter()
    category_rows: dict[str, list[tuple[dict[str, object], dict[str, object], dict[str, object]]]] = {}
    for question_id, question in expected.items():
        s, b = system[question_id], baseline[question_id]
        paired_status[(s["status"], b["status"])] += 1
        paired_routes[(s.get("route"), b.get("route"))] += 1
        category_rows.setdefault(str(question["category"]), []).append((question, s, b))

    def rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    by_category: dict[str, object] = {}
    for category, rows in sorted(category_rows.items()):
        n = len(rows)
        by_category[category] = {
            "question_count": n,
            "system_expected_status_match_rate": rate(
                sum(s["status"] in q["expected_status"] for q, s, _ in rows), n
            ),
            "baseline_expected_status_match_rate": rate(
                sum(b["status"] in q["expected_status"] for q, _, b in rows), n
            ),
            "system_answered_rate": rate(sum(s["status"] == "answered" for _, s, _ in rows), n),
            "baseline_answered_rate": rate(sum(b["status"] == "answered" for _, _, b in rows), n),
            "system_error_count": sum(s["status"] == "error" for _, s, _ in rows),
            "baseline_error_count": sum(b["status"] == "error" for _, _, b in rows),
        }
    return {
        "schema_version": "offline-comparison-v1",
        "system_model": IMPLEMENTATION_VERSION,
        "baseline_model": OFFLINE_BASELINE_VERSION,
        "question_set_hash": system_report["question_set_hash"],
        "evaluation_window_id": system_report["evaluation_window_id"],
        "question_count": len(questions),
        "system_diagnostics": system_report.get("automatic_diagnostics"),
        "baseline_diagnostics": baseline_report.get("automatic_diagnostics"),
        "paired_status_counts": {
            f"{system}->{baseline}": count
            for (system, baseline), count in sorted(paired_status.items())
        },
        "paired_route_counts": {
            f"{system}->{baseline}": count
            for (system, baseline), count in sorted(paired_routes.items(), key=lambda item: str(item[0]))
        },
        "by_category": by_category,
        "interpretation": "Engineering diagnostics only; no semantic correctness or superiority claim.",
    }
