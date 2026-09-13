from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from adc_evidence.evaluation.benchmark import (
    BENCHMARK_SCHEMA_VERSION,
    IMPLEMENTATION_VERSION,
    OFFLINE_BASELINE_VERSION,
    _system_row,
    automatic_diagnostics,
)
from adc_evidence.evaluation.human_review import question_id_sha256
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.workbench import evidence_data_version


HOLDOUT_SCHEMA_VERSION = "v0.6-public-holdout-v1"
HOLDOUT_VERSION = "v0.6-public-holdout-20q-2026-09-13"


def _digest(rows: list[dict[str, object]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_holdout_questions(path: Path) -> list[dict[str, object]]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]
    ids = [str(row.get("question_id", "")) for row in rows]
    if not rows or len(ids) != len(set(ids)) or any(not item for item in ids):
        raise ValueError("Holdout must contain unique nonempty question_id values")
    for row in rows:
        if not str(row.get("question", "")).strip():
            raise ValueError(f"Missing question text for {row.get('question_id')}")
        if row.get("expected_route") not in {
            "structured_fact",
            "comparison",
            "trial_lookup",
            "literature_evidence",
            "change_query",
            "refusal",
        }:
            raise ValueError(f"Invalid expected route for {row.get('question_id')}")
        if not row.get("expected_status"):
            raise ValueError(f"Missing expected status for {row.get('question_id')}")
        row.setdefault("split", "holdout")
        row.setdefault("evaluation_use", "public_smoke_holdout")
    return rows


def _normalized_question(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def validate_holdout_disjoint(
    holdout_questions: list[dict[str, object]],
    exposed_questions: list[dict[str, object]],
) -> dict[str, object]:
    """Fail closed if holdout wording or identifiers overlap exposed questions."""
    holdout_ids = {
        str(row.get("question_id", "")) for row in holdout_questions if str(row.get("question_id", ""))
    }
    exposed_ids = {
        str(row.get("question_id", "")) for row in exposed_questions if str(row.get("question_id", ""))
    }
    id_overlaps = sorted(holdout_ids & exposed_ids)
    if id_overlaps:
        raise ValueError(f"Holdout overlaps exposed question IDs: {id_overlaps}")
    exposed_by_text: dict[str, list[str]] = {}
    for row in exposed_questions:
        key = _normalized_question(row.get("question"))
        if key:
            exposed_by_text.setdefault(key, []).append(str(row.get("question_id", "")))
    overlaps = []
    for row in holdout_questions:
        key = _normalized_question(row.get("question"))
        if key in exposed_by_text:
            overlaps.append(
                {
                    "holdout_question_id": str(row["question_id"]),
                    "exposed_question_ids": sorted(exposed_by_text[key]),
                }
            )
    if overlaps:
        raise ValueError(f"Holdout overlaps exposed question text: {overlaps}")
    return {
        "status": "disjoint",
        "holdout_question_count": len(holdout_questions),
        "exposed_question_count": len(exposed_questions),
        "overlap_count": 0,
        "question_id_overlap_count": 0,
    }


def holdout_manifest(questions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": HOLDOUT_SCHEMA_VERSION,
        "question_set_version": HOLDOUT_VERSION,
        "question_set_hash": f"sha256:{_digest(questions)}",
        "question_id_sha256": question_id_sha256(
            str(row["question_id"]) for row in questions
        ),
        "question_count": len(questions),
        "evaluation_use": {
            "status": "public_smoke_holdout",
            "eligible_for_unseen_test_claim": False,
            "reason": (
                "The questions are public and may have informed development; use them only "
                "for reproducible smoke checks, not a confirmation claim."
            ),
            "confirmation_requires": "A separately frozen, access-controlled holdout with human review.",
        },
    }


def run_public_holdout(
    *,
    database_path: Path,
    questions: list[dict[str, object]],
    evaluation_window_id: str,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    manifest = holdout_manifest(questions)
    evaluated_at = evaluated_at or datetime.now(UTC).isoformat()
    system_service = EvidenceAnsweringService(
        database_path=database_path,
        generator=ExtractiveGenerator(),
    )
    baseline_service = EvidenceAnsweringService(
        database_path=None,
        retriever=HybridRetriever(database_path=database_path),
        generator=ExtractiveGenerator(),
    )
    arms = {}
    for arm, service, model in (
        ("adc_evidence", system_service, IMPLEMENTATION_VERSION),
        ("offline_rag_baseline", baseline_service, OFFLINE_BASELINE_VERSION),
    ):
        outputs = [_system_row(row, service.answer(str(row["question"]))) for row in questions]
        arms[arm] = {
            "run_id": f"{arm}-{uuid4().hex[:12]}",
            "arm": arm,
            "model": model,
            "network_enabled": False,
            "evaluated_at": evaluated_at,
            "automatic_diagnostics": automatic_diagnostics(outputs, questions),
            "questions": outputs,
        }
    return {
        **manifest,
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at,
        "database_data_version": evidence_data_version(database_path),
        "arms": arms,
    }
