"""Strict ingestion of human review labels for paired paper statistics.

This module deliberately accepts only labels whose provenance explicitly says
that a person produced or adjudicated them.  Automatic diagnostics and
AI-assisted first-pass records are useful for triage, but cannot silently
become the correctness reference used in a paper.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Iterable

from adc_evidence.evaluation.statistics import paired_binary_summary


HUMAN_REVIEW_ORIGINS = frozenset({"human_independent", "human_adjudicated"})


def load_human_paired_reviews(path: Path) -> list[dict[str, object]]:
    """Load one paired binary review record per question from JSONL."""
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Review line {line_number} must be an object")
        rows.append(row)
    return rows


def validate_human_paired_reviews(
    rows: Iterable[dict[str, object]],
) -> list[dict[str, object]]:
    """Validate provenance and shape before labels enter statistical code."""
    validated = list(rows)
    if not validated:
        raise ValueError("At least one human review label is required")
    question_ids: set[str] = set()
    for index, row in enumerate(validated, 1):
        question_id = row.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError(f"Row {index} needs a nonempty question_id")
        if question_id in question_ids:
            raise ValueError(f"Duplicate question_id: {question_id}")
        question_ids.add(question_id)
        origin = row.get("review_origin")
        if origin not in HUMAN_REVIEW_ORIGINS:
            raise ValueError(
                "Only human_independent or human_adjudicated labels are accepted; "
                f"row {index} has review_origin={origin!r}"
            )
        for field in ("system_correct", "baseline_correct"):
            if not isinstance(row.get(field), bool):
                raise ValueError(f"Row {index} field {field} must be boolean")
    return validated


def summarize_human_paired_reviews(
    rows: Iterable[dict[str, object]],
    *,
    confidence: float = 0.95,
    bootstrap_iterations: int = 10_000,
    seed: int = 0,
) -> dict[str, object]:
    """Compute paired statistics from explicitly human-produced labels."""
    validated = validate_human_paired_reviews(rows)
    summary = paired_binary_summary(
        [bool(row["system_correct"]) for row in validated],
        [bool(row["baseline_correct"]) for row in validated],
        confidence=confidence,
        bootstrap_iterations=bootstrap_iterations,
        seed=seed,
    )
    return {
        "schema_version": "v0.6-human-paired-review-v1",
        "review_origin_counts": dict(
            sorted(Counter(str(row["review_origin"]) for row in validated).items())
        ),
        "question_ids": [str(row["question_id"]) for row in validated],
        "human_review_required": True,
        "method_note": (
            "Labels are accepted only from independent human review or human adjudication; "
            "AI-assisted and automatic labels are rejected."
        ),
        "paired_statistics": summary,
    }


def summarize_inter_rater_agreement(
    rows: Iterable[dict[str, object]],
    *,
    field: str = "answer_verdict",
) -> dict[str, object]:
    """Compute agreement for exactly two independent human labels per question.

    Reviewer identities are intentionally excluded from the returned report.
    ``human_adjudicated`` is not accepted here because an adjudication is a
    resolved label, not an independent second rating.
    """
    records = list(rows)
    if not records:
        raise ValueError("At least one pair of human ratings is required")
    by_question: dict[str, dict[str, str]] = {}
    for index, row in enumerate(records, 1):
        question_id = row.get("question_id")
        slot = row.get("reviewer_slot")
        if not isinstance(question_id, str) or not question_id.strip():
            raise ValueError(f"Row {index} needs a nonempty question_id")
        if slot not in {"primary", "secondary"}:
            raise ValueError(f"Row {index} reviewer_slot must be primary or secondary")
        if row.get("review_origin") != "human_independent":
            raise ValueError("Inter-rater agreement requires human_independent ratings")
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Row {index} field {field} must be a nonempty string")
        slots = by_question.setdefault(question_id, {})
        if slot in slots:
            raise ValueError(f"Duplicate {slot} rating for question_id: {question_id}")
        slots[slot] = value
    if any(set(slots) != {"primary", "secondary"} for slots in by_question.values()):
        raise ValueError("Every question must have exactly one primary and one secondary rating")

    pairs = [
        (slots["primary"], slots["secondary"])
        for _, slots in sorted(by_question.items())
    ]
    labels = sorted({label for pair in pairs for label in pair})
    observed_agreement = sum(primary == secondary for primary, secondary in pairs) / len(pairs)
    primary_counts = Counter(primary for primary, _ in pairs)
    secondary_counts = Counter(secondary for _, secondary in pairs)
    expected_agreement = sum(
        primary_counts[label] * secondary_counts[label] for label in labels
    ) / (len(pairs) ** 2)
    kappa = (
        1.0
        if expected_agreement == 1.0
        else (observed_agreement - expected_agreement) / (1.0 - expected_agreement)
    )
    return {
        "schema_version": "v0.6-inter-rater-agreement-v1",
        "field": field,
        "question_count": len(pairs),
        "observed_agreement_rate": round(observed_agreement, 6),
        "disagreement_count": sum(primary != secondary for primary, secondary in pairs),
        "cohens_kappa": round(kappa, 6),
        "label_set": labels,
        "human_review_required": True,
        "method_note": "Two independent human ratings per question; adjudicated labels are excluded.",
    }
