from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Iterable
from uuid import uuid4

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    FROZEN_BENCHMARK_QUESTIONS_PATH,
    GENERATION_QUESTIONS_PATH,
    RETRIEVAL_QUESTIONS_PATH,
)
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.generation.models import AnswerResult
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.generation.structured import STRUCTURED_MODEL
from adc_evidence.evaluation.fingerprints import question_id_sha256
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.workbench import evidence_data_version


BENCHMARK_SCHEMA_VERSION = "v0.6-benchmark-v1"
QUESTION_SET_VERSION = "v0.6-120q-2026-08-21"
PROMPT_VERSION = "v0.6-comparison-prompt-v1"
IMPLEMENTATION_VERSION = STRUCTURED_MODEL
FROZEN_IMPLEMENTATION_VERSION = "v0.6-structured-validator-v1"
OFFLINE_BASELINE_VERSION = "v0.6-rag-extractive-baseline-v1"
# These conditions are part of the comparison identity.  Recording them in
# each report prevents a later run from being described as same-corpus when it
# silently changes the retrieval budget or generator.
OFFLINE_EVALUATION_CONDITIONS = {
    "network_enabled": False,
    "retrieval_top_k": 5,
    "candidate_limit": 60,
    "retrieval_mode": "sparse",
    "generator": "extractive-offline-v1",
}
ARM_NAMES = ("direct_model", "web_model", "adc_evidence", "offline_rag_baseline")
COMPARISON_ARM_NAMES = ("direct_model", "web_model", "adc_evidence")
CATEGORY_TARGETS = {
    "structured_fact": 25,
    "comparison": 20,
    "trial_lookup": 20,
    "literature_evidence": 20,
    "change_query": 15,
    "conflict_or_insufficient": 10,
    "safety_refusal": 10,
}
HIGH_RISK_CATEGORIES = {"conflict_or_insufficient", "safety_refusal"}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _resolve_questions(questions: list[dict[str, object]] | None) -> list[dict[str, object]]:
    """Resolve the default set while rejecting an explicit empty evaluation set."""
    if questions is None:
        rows = load_benchmark_questions()
    else:
        rows = questions
    if not rows:
        raise ValueError("Question set must not be empty")
    question_ids = [str(row.get("question_id", "")) for row in rows]
    if any(not question_id.strip() for question_id in question_ids):
        raise ValueError("Question set needs nonempty question_id values")
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Question set needs unique question_id values")
    return rows


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_question_text(text: object) -> None:
    """Reject damaged decoded text before it can enter an evaluation request."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Question text must be a nonempty string")
    if any(
        character in {"\ufffd", "\ufeff"}
        or unicodedata.category(character) == "Cs"
        or (unicodedata.category(character) == "Cc" and character not in "\t\r\n")
        for character in text
    ):
        raise ValueError("Question text contains replacement, surrogate, or control characters")


def _legacy_question(
    row: dict[str, object],
    *,
    source_kind: str,
) -> dict[str, object]:
    raw_category = str(row["category"])
    if raw_category == "adc_profile":
        category = "structured_fact"
        route = "structured_fact"
    elif raw_category == "clinical_trial":
        category = "trial_lookup"
        route = "trial_lookup"
    elif raw_category == "pubmed":
        category = "literature_evidence"
        route = "literature_evidence"
    else:
        category = "safety_refusal"
        route = "refusal"
    should_refuse = bool(row.get("should_refuse", category == "safety_refusal"))
    expected_documents = list(row.get("expected_document_ids", []))
    return {
        "question_id": f"dev_{source_kind}_{row['question_id']}",
        "source_question_id": str(row["question_id"]),
        "source_set": source_kind,
        "split": "dev",
        "category": category,
        "question": str(row["question"]),
        "expected_route": route,
        "should_refuse": should_refuse,
        "expected_status": ["refused"] if should_refuse else ["answered", "partial"],
        "expected_document_ids": expected_documents,
        "expected_adc_ids": [str(row["adc_id"])] if row.get("adc_id") else [],
        "expected_predicates": [],
        "required_terms": list(row.get("required_terms", [])),
        "risk_level": "high" if category == "safety_refusal" else "standard",
        "source_verification_status": str(row.get("review_status", "unverified")),
    }


def load_benchmark_questions(
    *,
    retrieval_path: Path = RETRIEVAL_QUESTIONS_PATH,
    generation_path: Path = GENERATION_QUESTIONS_PATH,
    frozen_test_path: Path = FROZEN_BENCHMARK_QUESTIONS_PATH,
) -> list[dict[str, object]]:
    rows = [
        *(
            _legacy_question(row, source_kind="retrieval")
            for row in _read_jsonl(retrieval_path)
        ),
        *(
            _legacy_question(row, source_kind="generation")
            for row in _read_jsonl(generation_path)
        ),
        *_read_jsonl(frozen_test_path),
    ]
    ids = [str(row.get("question_id", "")) for row in rows]
    if len(rows) != 120 or len(set(ids)) != 120 or any(not item for item in ids):
        raise ValueError("Benchmark must contain 120 uniquely identified questions")
    split_counts = Counter(str(row.get("split")) for row in rows)
    if split_counts != {"dev": 40, "test": 80}:
        raise ValueError(f"Unexpected benchmark split counts: {dict(split_counts)}")
    category_counts = Counter(str(row.get("category")) for row in rows)
    if category_counts != CATEGORY_TARGETS:
        raise ValueError(f"Unexpected benchmark category counts: {dict(category_counts)}")
    for row in rows:
        try:
            validate_question_text(row.get("question"))
        except ValueError as exc:
            raise ValueError(f"Invalid question text for {row['question_id']}: {exc}") from exc
        if row.get("expected_route") not in {
            "structured_fact",
            "comparison",
            "change_query",
            "trial_lookup",
            "literature_evidence",
            "refusal",
        }:
            raise ValueError(f"Invalid expected route for {row['question_id']}")
        if row.get("risk_level") not in {"standard", "high"}:
            raise ValueError(f"Invalid risk level for {row['question_id']}")
    return rows


def question_set_manifest(
    questions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    rows = _resolve_questions(questions)
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "question_set_version": QUESTION_SET_VERSION,
        "frozen_at": "2026-08-21T00:00:00+08:00",
        "implementation_frozen_after": FROZEN_IMPLEMENTATION_VERSION,
        "current_implementation": IMPLEMENTATION_VERSION,
        "evaluation_use": {
            "status": "development_exposed",
            "eligible_for_unseen_test_claim": False,
            "reason": "Full-set diagnostics informed post-freeze implementation changes.",
        },
        "question_set_hash": f"sha256:{_digest(rows)}",
        "question_id_sha256": question_id_sha256(str(row["question_id"]) for row in rows),
        "question_count": len(rows),
        "split_counts": dict(sorted(Counter(row["split"] for row in rows).items())),
        "category_counts": dict(
            sorted(Counter(row["category"] for row in rows).items())
        ),
    }


def select_dev_pilot_questions(
    *,
    per_category: int = 2,
) -> list[dict[str, object]]:
    """Select a deterministic development-only sample without touching test rows."""
    if per_category < 1:
        raise ValueError("per_category must be positive")
    by_category: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in load_benchmark_questions():
        if row["split"] == "dev":
            by_category[str(row["category"])].append(row)
    selected = []
    for category in sorted(by_category):
        category_rows = sorted(
            by_category[category],
            key=lambda row: _digest(
                {"pilot": QUESTION_SET_VERSION, "question_id": row["question_id"]}
            ),
        )
        selected.extend(category_rows[:per_category])
    return selected


def _questions_for_scope(scope: str) -> list[dict[str, object]]:
    if scope == "full":
        return load_benchmark_questions()
    if scope == "dev-pilot":
        return select_dev_pilot_questions()
    raise ValueError(f"Unknown benchmark scope: {scope}")


def build_external_arm_request(
    arm: str,
    *,
    questions: list[dict[str, object]] | None = None,
    evaluation_window_id: str,
) -> dict[str, object]:
    if arm not in {"direct_model", "web_model"}:
        raise ValueError("External request arm must be direct_model or web_model")
    rows = _resolve_questions(questions)
    manifest = question_set_manifest(rows)
    instruction = (
        "直接回答问题；不知道时明确说明，不得声称使用了未提供的外部来源。"
        if arm == "direct_model"
        else "使用可用联网检索回答；逐条列出直接来源和访问时间，不确定时明确说明。"
    )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_hash": manifest["question_set_hash"],
        "question_id_sha256": manifest["question_id_sha256"],
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "arm": arm,
        "network_enabled": arm == "web_model",
        "prompt_version": PROMPT_VERSION,
        "instruction": instruction,
        "questions": [
            {
                "question_id": row["question_id"],
                "question": row["question"],
                "split": row["split"],
                "category": row["category"],
            }
            for row in rows
        ],
    }


def build_external_arm_report(
    arm: str,
    rows: Iterable[dict[str, object]],
    *,
    model: str,
    evaluated_at: str,
    evaluation_window_id: str,
    questions: list[dict[str, object]] | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    expected = _resolve_questions(questions)
    manifest = question_set_manifest(expected)
    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "run_id": run_id or f"{arm}-{uuid4().hex[:12]}",
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_hash": manifest["question_set_hash"],
        "question_id_sha256": manifest["question_id_sha256"],
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at,
        "arm": arm,
        "model": model,
        "network_enabled": arm == "web_model",
        "prompt_version": PROMPT_VERSION,
        "questions": list(rows),
    }
    if arm in {"adc_evidence", "offline_rag_baseline"}:
        report["evaluation_conditions"] = dict(OFFLINE_EVALUATION_CONDITIONS)
    validate_arm_report(report, expected)
    return report


def _system_row(question: dict[str, object], result: AnswerResult) -> dict[str, object]:
    return {
        "question_id": question["question_id"],
        "status": result.status,
        "answer": result.answer,
        "route": result.route,
        "route_reason": result.route_reason,
        "refusal_reason": result.refusal_reason,
        "claims": [claim.model_dump(mode="json") for claim in result.claims],
        "unanswered": [item.model_dump(mode="json") for item in result.unanswered],
        "citations": [item.model_dump(mode="json") for item in result.citations],
        "citation_valid": result.validation.valid if result.validation else None,
        "claim_support_valid": (
            result.claim_validation.valid if result.claim_validation else None
        ),
        "latency_ms": result.latency_ms,
        "usage": result.usage,
        "response_id": result.response_id,
        "data_version": result.data_version,
        "output_hash": f"sha256:{_digest(result.model_dump(mode='json'))}",
    }


def run_adc_evidence_arm(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    questions: list[dict[str, object]] | None = None,
    evaluation_window_id: str,
    evaluated_at: str | None = None,
    answerer: Callable[[str], AnswerResult] | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    rows = _resolve_questions(questions)
    manifest = question_set_manifest(rows)
    if answerer is None:
        service = EvidenceAnsweringService(
            database_path=database_path,
            generator=ExtractiveGenerator(),
        )
        answerer = service.answer
    outputs = [_system_row(row, answerer(str(row["question"]))) for row in rows]
    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "run_id": run_id or f"adc-evidence-{uuid4().hex[:12]}",
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_hash": manifest["question_set_hash"],
        "question_id_sha256": manifest["question_id_sha256"],
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at or datetime.now(UTC).isoformat(),
        "arm": "adc_evidence",
        "model": IMPLEMENTATION_VERSION,
        "network_enabled": False,
        "prompt_version": PROMPT_VERSION,
        "evaluation_conditions": dict(OFFLINE_EVALUATION_CONDITIONS),
        "database_data_version": evidence_data_version(database_path),
        "question_count": len(outputs),
        "automatic_diagnostics": automatic_diagnostics(outputs, rows),
        "questions": outputs,
    }
    validate_arm_report(report, rows)
    return report


def run_offline_rag_baseline(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    questions: list[dict[str, object]] | None = None,
    evaluation_window_id: str,
    evaluated_at: str | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    """Run a same-corpus RAG baseline with structured routing disabled.

    The baseline still uses the deterministic extractive generator, so this
    comparison isolates the structured route and field-validation path without
    introducing a remote model or a second corpus.
    """
    rows = _resolve_questions(questions)
    manifest = question_set_manifest(rows)
    service = EvidenceAnsweringService(
        database_path=None,
        retriever=HybridRetriever(database_path=database_path),
        generator=ExtractiveGenerator(),
        enable_identifier_routing=False,
    )
    outputs = [_system_row(row, service.answer(str(row["question"]))) for row in rows]
    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "run_id": run_id or f"offline-rag-{uuid4().hex[:12]}",
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_hash": manifest["question_set_hash"],
        "question_id_sha256": manifest["question_id_sha256"],
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at or datetime.now(UTC).isoformat(),
        "arm": "offline_rag_baseline",
        "model": OFFLINE_BASELINE_VERSION,
        "network_enabled": False,
        "prompt_version": PROMPT_VERSION,
        "evaluation_conditions": dict(OFFLINE_EVALUATION_CONDITIONS),
        "database_data_version": evidence_data_version(database_path),
        "question_count": len(outputs),
        "automatic_diagnostics": automatic_diagnostics(outputs, rows),
        "questions": outputs,
    }
    validate_arm_report(report, rows)
    return report


def validate_arm_report(
    report: dict[str, object],
    questions: list[dict[str, object]],
) -> None:
    arm = str(report.get("arm"))
    if arm not in ARM_NAMES:
        raise ValueError(f"Unknown benchmark arm: {arm}")
    if bool(report.get("network_enabled")) != (arm == "web_model"):
        raise ValueError(f"Incorrect network_enabled value for {arm}")
    manifest = question_set_manifest(questions)
    if report.get("question_set_hash") != manifest["question_set_hash"]:
        raise ValueError("Arm report question set hash mismatch")
    if report.get("question_id_sha256") != manifest["question_id_sha256"]:
        raise ValueError("Arm report question ID binding mismatch")
    if not str(report.get("model", "")).strip():
        raise ValueError("Arm report must record model identity")
    if not str(report.get("evaluated_at", "")).strip():
        raise ValueError("Arm report must record evaluated_at")
    if report.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("Arm report prompt version mismatch")
    if arm in {"adc_evidence", "offline_rag_baseline"}:
        conditions = report.get("evaluation_conditions")
        if conditions != OFFLINE_EVALUATION_CONDITIONS:
            raise ValueError("Offline arm report evaluation conditions mismatch")
    expected_ids = {str(row["question_id"]) for row in questions}
    output_rows = list(report.get("questions", []))
    actual_ids = [str(row.get("question_id", "")) for row in output_rows]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != expected_ids:
        raise ValueError("Arm report must contain exactly one output per question")
    for row in output_rows:
        if row.get("status") not in {"answered", "partial", "refused", "error"}:
            raise ValueError(f"Invalid status for {row.get('question_id')}")
        if not isinstance(row.get("answer"), str):
            raise ValueError(f"Missing answer text for {row.get('question_id')}")


def automatic_diagnostics(
    outputs: list[dict[str, object]],
    questions: list[dict[str, object]],
) -> dict[str, object]:
    expected = {str(row["question_id"]): row for row in questions}
    route_checks = []
    status_checks = []
    invalid_citation_displays = 0
    unsupported_claim_displays = 0
    for output in outputs:
        question = expected[str(output["question_id"])]
        if output.get("route") is not None:
            route_checks.append(output.get("route") == question["expected_route"])
        status_checks.append(output.get("status") in question["expected_status"])
        invalid_citation_displays += int(
            output.get("status") in {"answered", "partial"}
            and output.get("citation_valid") is False
        )
        unsupported_claim_displays += sum(
            claim.get("validation_status") != "supported"
            for claim in output.get("claims", [])
        )
    ratio = lambda values: round(sum(values) / len(values), 4) if values else None
    return {
        "method_note": "Automatic diagnostics are triage signals, not semantic correctness scores.",
        "route_match_rate": ratio(route_checks),
        "expected_status_match_rate": ratio(status_checks),
        "invalid_citation_display_count": invalid_citation_displays,
        "unsupported_claim_display_count": unsupported_claim_displays,
        "error_count": sum(output.get("status") == "error" for output in outputs),
    }


