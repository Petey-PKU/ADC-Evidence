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
