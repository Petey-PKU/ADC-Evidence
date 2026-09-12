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
    BENCHMARK_BAD_CASE_PATH,
    BENCHMARK_IDENTITY_MAP_PATH,
    BENCHMARK_REGRESSION_CANDIDATES_PATH,
    BENCHMARK_REPORT_PATH,
    BENCHMARK_REVIEW_PACKET_PATH,
    BENCHMARK_SUMMARY_PATH,
    DEFAULT_DATABASE_PATH,
    FROZEN_BENCHMARK_QUESTIONS_PATH,
    GENERATION_QUESTIONS_PATH,
    RETRIEVAL_QUESTIONS_PATH,
)
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.generation.models import AnswerResult
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.generation.structured import STRUCTURED_MODEL
from adc_evidence.evaluation.human_review import question_id_sha256
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.workbench import evidence_data_version


BENCHMARK_SCHEMA_VERSION = "v0.6-benchmark-v1"
QUESTION_SET_VERSION = "v0.6-120q-2026-08-21"
PROMPT_VERSION = "v0.6-comparison-prompt-v1"
IMPLEMENTATION_VERSION = STRUCTURED_MODEL
FROZEN_IMPLEMENTATION_VERSION = "v0.6-structured-validator-v1"
OFFLINE_BASELINE_VERSION = "v0.6-rag-extractive-baseline-v1"
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
        return load_benchmark_questions()
    if not questions:
        raise ValueError("Question set must not be empty")
    return questions


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
        "source_review_status": str(row.get("review_status", "unreviewed")),
    }


def _assign_review_scope(rows: list[dict[str, object]]) -> None:
    high_risk = [row for row in rows if row["category"] in HIGH_RISK_CATEGORIES]
    ordinary = [row for row in rows if row["category"] not in HIGH_RISK_CATEGORIES]
    ordinary_double_count = math.ceil(len(ordinary) * 0.25)
    selected_ordinary = {
        str(row["question_id"])
        for row in sorted(
            ordinary,
            key=lambda item: _digest(
                {"version": QUESTION_SET_VERSION, "question_id": item["question_id"]}
            ),
        )[:ordinary_double_count]
    }
    for row in rows:
        double_review = (
            row["category"] in HIGH_RISK_CATEGORIES
            or str(row["question_id"]) in selected_ordinary
        )
        row["review_tier"] = "double" if double_review else "single"
        row["second_review_required"] = double_review
    if len(high_risk) != 20 or ordinary_double_count != 25:
        raise ValueError("Benchmark review scope must contain 20 high-risk and 25 ordinary double reviews")


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
    _assign_review_scope(rows)
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
        "review_scope": {
            "double_review_question_count": sum(
                bool(row["second_review_required"]) for row in rows
            ),
            "high_risk_double_review_count": sum(
                row["category"] in HIGH_RISK_CATEGORIES for row in rows
            ),
            "ordinary_double_review_count": sum(
                bool(row["second_review_required"])
                and row["category"] not in HIGH_RISK_CATEGORIES
                for row in rows
            ),
        },
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
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at,
        "arm": arm,
        "model": model,
        "network_enabled": arm == "web_model",
        "prompt_version": PROMPT_VERSION,
        "questions": list(rows),
    }
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
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at or datetime.now(UTC).isoformat(),
        "arm": "adc_evidence",
        "model": IMPLEMENTATION_VERSION,
        "network_enabled": False,
        "prompt_version": PROMPT_VERSION,
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
    )
    outputs = [_system_row(row, service.answer(str(row["question"]))) for row in rows]
    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "run_id": run_id or f"offline-rag-{uuid4().hex[:12]}",
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_hash": manifest["question_set_hash"],
        "evaluation_use": manifest["evaluation_use"],
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at or datetime.now(UTC).isoformat(),
        "arm": "offline_rag_baseline",
        "model": OFFLINE_BASELINE_VERSION,
        "network_enabled": False,
        "prompt_version": PROMPT_VERSION,
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
    if not str(report.get("model", "")).strip():
        raise ValueError("Arm report must record model identity")
    if not str(report.get("evaluated_at", "")).strip():
        raise ValueError("Arm report must record evaluated_at")
    if report.get("prompt_version") != PROMPT_VERSION:
        raise ValueError("Arm report prompt version mismatch")
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


def _review_claims(source: dict[str, object]) -> list[dict[str, object]]:
    """Normalize all arms into the same identity-neutral atomic-claim shape."""
    source_claims = list(source.get("claims", []))
    if source_claims:
        texts = [
            {
                "text": str(claim.get("text", "")).strip(),
                "citation_ids": list(claim.get("citation_ids", [])),
            }
            for claim in source_claims
            if str(claim.get("text", "")).strip()
        ]
    else:
        answer = str(source.get("answer", "")).strip()
        parts = [
            part.strip(" -\t")
            for part in re.split(r"(?<=[。！？!?])\s*|[\r\n]+", answer)
            if part.strip(" -\t")
        ]
        texts = [
            {
                "text": part,
                "citation_ids": sorted(
                    set(re.findall(r"\[(S\d+)\]", part)),
                    key=lambda item: int(item[1:]),
                ),
            }
            for part in parts
        ]
    return [
        {
            "claim_id": f"C{index}",
            "text": row["text"],
            "citation_ids": row["citation_ids"],
        }
        for index, row in enumerate(texts, start=1)
    ]


def build_blinded_review_packet(
    reports: Iterable[dict[str, object]],
    *,
    questions: list[dict[str, object]] | None = None,
    run_id: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    rows = _resolve_questions(questions)
    reports = list(reports)
    if {str(report.get("arm")) for report in reports} != set(COMPARISON_ARM_NAMES):
        raise ValueError("Comparison requires direct_model, web_model and adc_evidence arms")
    for report in reports:
        validate_arm_report(report, rows)
    windows = {str(report["evaluation_window_id"]) for report in reports}
    hashes = {str(report["question_set_hash"]) for report in reports}
    if len(windows) != 1 or len(hashes) != 1:
        raise ValueError("All comparison arms must use one evaluation window and question set")
    comparison_run_id = run_id or f"cmp-{uuid4().hex[:12]}"
    by_arm = {
        str(report["arm"]): {
            str(item["question_id"]): item for item in report["questions"]
        }
        for report in reports
    }
    report_meta = {str(report["arm"]): report for report in reports}
    packet_rows: list[dict[str, object]] = []
    mapping_rows: list[dict[str, object]] = []
    for question in rows:
        question_id = str(question["question_id"])
        ordered_arms = sorted(
            COMPARISON_ARM_NAMES,
            key=lambda arm: _digest(
                {
                    "question_set_hash": next(iter(hashes)),
                    "question_id": question_id,
                    "arm": arm,
                }
            ),
        )
        candidates = []
        for index, arm in enumerate(ordered_arms):
            blind_arm = chr(ord("A") + index)
            source = by_arm[arm][question_id]
            candidate_id = f"{comparison_run_id}:{question_id}:{blind_arm}"
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "blind_arm": blind_arm,
                    "status": source["status"],
                    "answer": source["answer"],
                    "citations": list(source.get("citations", [])),
                    "claims": _review_claims(source),
                }
            )
            mapping_rows.append(
                {
                    "candidate_id": candidate_id,
                    "question_id": question_id,
                    "blind_arm": blind_arm,
                    "arm": arm,
                    "model": report_meta[arm]["model"],
                    "arm_run_id": report_meta[arm]["run_id"],
                }
            )
        packet_rows.append(
            {
                "question_id": question_id,
                "question": question["question"],
                "split": question["split"],
                "category": question["category"],
                "risk_level": question["risk_level"],
                "should_refuse": question["should_refuse"],
                "expected_document_ids": list(question.get("expected_document_ids", [])),
                "second_review_required": question["second_review_required"],
                "candidates": candidates,
            }
        )
    identity_map = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "comparison_run_id": comparison_run_id,
        "evaluation_window_id": next(iter(windows)),
        "question_set_hash": next(iter(hashes)),
        "mapping": mapping_rows,
    }
    mapping_hash = f"sha256:{_digest(identity_map)}"
    packet = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "comparison_run_id": comparison_run_id,
        "evaluation_window_id": next(iter(windows)),
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_hash": next(iter(hashes)),
        "blind_mapping_hash": mapping_hash,
        "blinded": True,
        "identity_disclosure_rule": "Reveal mapping only after answer and evidence verdicts are saved.",
        "question_count": len(packet_rows),
        "candidate_count": len(mapping_rows),
        "questions": packet_rows,
    }
    return packet, identity_map


def validate_blinded_pair(
    packet: dict[str, object],
    identity_map: dict[str, object],
) -> None:
    """Validate the separately stored blind packet and post-review identity map."""
    if packet.get("blinded") is not True:
        raise ValueError("Review packet must be marked as blinded")
    for field in ("comparison_run_id", "evaluation_window_id", "question_set_hash"):
        if packet.get(field) != identity_map.get(field):
            raise ValueError(f"Blind packet and identity map disagree on {field}")
    if packet.get("blind_mapping_hash") != f"sha256:{_digest(identity_map)}":
        raise ValueError("Blind identity map hash mismatch")
    packet_candidates = {
        str(candidate["candidate_id"])
        for question in packet.get("questions", [])
        for candidate in question.get("candidates", [])
    }
    mapped_candidates = {
        str(row["candidate_id"]) for row in identity_map.get("mapping", [])
    }
    if packet_candidates != mapped_candidates:
        raise ValueError("Blind packet and identity map candidate sets differ")
    if len(mapped_candidates) != int(packet.get("candidate_count", -1)):
        raise ValueError("Blind packet candidate count mismatch")


_VERDICT_SCORE = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}


def _effective_reviews(
    packet: dict[str, object],
    reviews: Iterable[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    reviews_by_candidate: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    for review in reviews:
        slot = str(review.get("reviewer_slot"))
        if slot not in {"primary", "secondary", "adjudicator"}:
            raise ValueError("reviewer_slot must be primary, secondary or adjudicator")
        origin = review.get("review_origin")
        expected_origin = "human_adjudicated" if slot == "adjudicator" else "human_independent"
        if origin != expected_origin:
            raise ValueError(
                f"{slot} reviews require review_origin={expected_origin!r}"
            )
        reviews_by_candidate[str(review["candidate_id"])][slot] = review
    effective: dict[str, dict[str, object]] = {}
    required_count = 0
    completed_required_count = 0
    double_pairs = 0
    agreeing_pairs = 0
    unresolved_disagreements = 0
    core_fields = (
        "answer_verdict",
        "evidence_verdict",
        "citation_verdict",
        "completeness_verdict",
        "refusal_verdict",
    )
    for question in packet["questions"]:
        for candidate in question["candidates"]:
            candidate_id = str(candidate["candidate_id"])
            slots = reviews_by_candidate.get(candidate_id, {})
            required_slots = ["primary"]
            if question["second_review_required"]:
                required_slots.append("secondary")
            required_count += len(required_slots)
            completed_required_count += sum(slot in slots for slot in required_slots)
            primary = slots.get("primary")
            secondary = slots.get("secondary")
            disagreement = False
            if question["second_review_required"] and primary and secondary:
                double_pairs += 1
                disagreement = any(primary.get(field) != secondary.get(field) for field in core_fields)
                agreeing_pairs += int(not disagreement)
                if disagreement and "adjudicator" not in slots:
                    unresolved_disagreements += 1
            chosen = slots.get("adjudicator") or primary
            if chosen is not None and not (
                question["second_review_required"] and secondary is None
            ) and not (disagreement and "adjudicator" not in slots):
                effective[candidate_id] = chosen
    return effective, {
        "required_review_count": required_count,
        "completed_required_review_count": completed_required_count,
        "required_review_coverage": (
            round(completed_required_count / required_count, 4) if required_count else 0.0
        ),
        "double_review_pair_count": double_pairs,
        "exact_agreement_rate": (
            round(agreeing_pairs / double_pairs, 4) if double_pairs else None
        ),
        "unresolved_disagreement_count": unresolved_disagreements,
    }


def aggregate_human_scores(
    packet: dict[str, object],
    identity_map: dict[str, object],
    reviews: Iterable[dict[str, object]],
) -> dict[str, object]:
    validate_blinded_pair(packet, identity_map)
    reviews = list(reviews)
    effective, coverage = _effective_reviews(packet, reviews)
    mapping = {
        str(row["candidate_id"]): str(row["arm"])
        for row in identity_map["mapping"]
    }
    by_arm: dict[str, list[dict[str, object]]] = defaultdict(list)
    for candidate_id, review in effective.items():
        by_arm[mapping[candidate_id]].append(review)

    def metric(items: list[dict[str, object]], field: str) -> float | None:
        values = [
            _VERDICT_SCORE[str(item[field])]
            for item in items
            if item.get(field) in _VERDICT_SCORE
        ]
        return round(sum(values) / len(values), 4) if values else None

    arm_metrics = {
        arm: {
            "adjudicated_candidate_count": len(by_arm.get(arm, [])),
            "answer_correctness": metric(by_arm.get(arm, []), "answer_verdict"),
            "evidence_support": metric(by_arm.get(arm, []), "evidence_verdict"),
            "citation_correctness": metric(by_arm.get(arm, []), "citation_verdict"),
            "multi_item_completeness": metric(
                by_arm.get(arm, []), "completeness_verdict"
            ),
            "refusal_correctness": metric(by_arm.get(arm, []), "refusal_verdict"),
        }
        for arm in COMPARISON_ARM_NAMES
    }
    complete = (
        coverage["required_review_coverage"] == 1.0
        and coverage["unresolved_disagreement_count"] == 0
    )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "comparison_run_id": packet["comparison_run_id"],
        "status": "complete" if complete else "awaiting_human_review",
        "method_note": (
            "Metrics use human or adjudicated verdicts only; automatic diagnostics are not substituted."
        ),
        "review_coverage": coverage,
        "arm_metrics": arm_metrics,
    }


def build_benchmark_bad_case_report(
    packet: dict[str, object],
    identity_map: dict[str, object],
    reviews: Iterable[dict[str, object]],
) -> dict[str, object]:
    validate_blinded_pair(packet, identity_map)
    reviews = list(reviews)
    effective, coverage = _effective_reviews(packet, reviews)
    mapping = {
        str(row["candidate_id"]): row for row in identity_map["mapping"]
    }
    question_by_candidate = {
        str(candidate["candidate_id"]): question
        for question in packet["questions"]
        for candidate in question["candidates"]
    }
    cases = []
    for candidate_id, review in effective.items():
        bad = any(
            review.get(field) in {"partial", "incorrect"}
            for field in (
                "answer_verdict",
                "evidence_verdict",
                "citation_verdict",
                "completeness_verdict",
            )
        ) or review.get("refusal_verdict") == "incorrect"
        if not bad:
            continue
        question = question_by_candidate[candidate_id]
        identity = mapping[candidate_id]
        cases.append(
            {
                "candidate_id": candidate_id,
                "question_id": question["question_id"],
                "category": question["category"],
                "arm": identity["arm"],
                "model": identity["model"],
                "severity": review.get("severity", "medium"),
                "error_categories": list(review.get("error_categories", [])),
                "verdicts": {
                    field: review.get(field)
                    for field in (
                        "answer_verdict",
                        "evidence_verdict",
                        "citation_verdict",
                        "completeness_verdict",
                        "refusal_verdict",
                    )
                },
            }
        )
    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "comparison_run_id": packet["comparison_run_id"],
        "review_status": (
            "complete"
            if coverage["required_review_coverage"] == 1.0
            and coverage["unresolved_disagreement_count"] == 0
            else "incomplete"
        ),
        "method_note": "Human-confirmed cases only; reviewer identities and notes are excluded.",
        "summary": {
            "human_bad_case_count": len(cases),
            "by_arm": dict(sorted(Counter(case["arm"] for case in cases).items())),
            "by_category": dict(
                sorted(Counter(case["category"] for case in cases).items())
            ),
            **coverage,
        },
        "cases": cases,
    }


def build_regression_candidates(
    packet: dict[str, object],
    identity_map: dict[str, object],
    reviews: Iterable[dict[str, object]],
    *,
    questions: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    validate_blinded_pair(packet, identity_map)
    rows = _resolve_questions(questions)
    by_question = {str(row["question_id"]): row for row in rows}
    effective, _ = _effective_reviews(packet, list(reviews))
    identity = {
        str(row["candidate_id"]): row for row in identity_map["mapping"]
    }
    candidates = []
    for candidate_id, review in effective.items():
        mapping = identity[candidate_id]
        if mapping["arm"] != "adc_evidence":
            continue
        is_bad = any(
            review.get(field) in {"partial", "incorrect"}
            for field in (
                "answer_verdict",
                "evidence_verdict",
                "citation_verdict",
                "completeness_verdict",
            )
        ) or review.get("refusal_verdict") == "incorrect"
        if not is_bad:
            continue
        source = by_question[str(mapping["question_id"])]
        payload = {
            "question_id": f"reg_{source['question_id']}",
            "question": source["question"],
            "category": source["category"],
            "expected_route": source["expected_route"],
            "should_refuse": source["should_refuse"],
            "expected_status": source["expected_status"],
            "expected_document_ids": list(source.get("expected_document_ids", [])),
            "expected_adc_ids": list(source.get("expected_adc_ids", [])),
            "expected_predicates": list(source.get("expected_predicates", [])),
            "required_terms": list(source.get("required_terms", [])),
            "regression_for": source["question_id"],
            "source_comparison_run_id": packet["comparison_run_id"],
            "error_categories": list(review.get("error_categories", [])),
            "adjudicated_severity": review.get("severity", "medium"),
        }
        payload["content_hash"] = f"sha256:{_digest(payload)}"
        candidates.append(payload)
    return sorted(candidates, key=lambda item: str(item["question_id"]))


def render_jsonl(rows: Iterable[dict[str, object]]) -> str:
    return "".join(_canonical(row) + "\n" for row in rows)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_jsonl(rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the v0.6 three-arm benchmark workflow.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    request_parser = subparsers.add_parser("prepare-request")
    request_parser.add_argument("--arm", required=True, choices=("direct_model", "web_model"))
    request_parser.add_argument("--window-id", required=True)
    request_parser.add_argument("--output", type=Path, required=True)
    request_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    external_parser = subparsers.add_parser("import-external")
    external_parser.add_argument(
        "--arm", required=True, choices=("direct_model", "web_model")
    )
    external_parser.add_argument("--responses", type=Path, required=True)
    external_parser.add_argument("--model", required=True)
    external_parser.add_argument("--evaluated-at", required=True)
    external_parser.add_argument("--window-id", required=True)
    external_parser.add_argument("--output", type=Path, required=True)
    external_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    run_external_parser = subparsers.add_parser("run-external")
    run_external_parser.add_argument(
        "--arm", required=True, choices=("direct_model", "web_model")
    )
    run_external_parser.add_argument("--window-id", required=True)
    run_external_parser.add_argument("--output", type=Path, required=True)
    run_external_parser.add_argument(
        "--scope", choices=("full", "dev-pilot"), default="dev-pilot"
    )
    system_parser = subparsers.add_parser("run-system")
    system_parser.add_argument("--window-id", required=True)
    system_parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    system_parser.add_argument("--output", type=Path, required=True)
    system_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    baseline_parser = subparsers.add_parser("run-offline-baseline")
    baseline_parser.add_argument("--window-id", required=True)
    baseline_parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    baseline_parser.add_argument("--output", type=Path, required=True)
    baseline_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    compare_parser = subparsers.add_parser("compare-offline")
    compare_parser.add_argument("--system-report", type=Path, required=True)
    compare_parser.add_argument("--baseline-report", type=Path, required=True)
    compare_parser.add_argument("--output", type=Path, required=True)
    compare_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    assemble_parser = subparsers.add_parser("assemble")
    assemble_parser.add_argument("--direct-report", type=Path, required=True)
    assemble_parser.add_argument("--web-report", type=Path, required=True)
    assemble_parser.add_argument("--system-report", type=Path, required=True)
    assemble_parser.add_argument("--packet", type=Path, default=BENCHMARK_REVIEW_PACKET_PATH)
    assemble_parser.add_argument("--identity-map", type=Path, default=BENCHMARK_IDENTITY_MAP_PATH)
    assemble_parser.add_argument("--scope", choices=("full", "dev-pilot"), default="full")
    summarize_parser = subparsers.add_parser("summarize")
    summarize_parser.add_argument("--packet", type=Path, default=BENCHMARK_REVIEW_PACKET_PATH)
    summarize_parser.add_argument("--identity-map", type=Path, default=BENCHMARK_IDENTITY_MAP_PATH)
    summarize_parser.add_argument("--reviews", type=Path, required=True)
    summarize_parser.add_argument("--summary", type=Path, default=BENCHMARK_SUMMARY_PATH)
    summarize_parser.add_argument("--bad-cases", type=Path, default=BENCHMARK_BAD_CASE_PATH)
    summarize_parser.add_argument(
        "--regression-candidates",
        type=Path,
        default=BENCHMARK_REGRESSION_CANDIDATES_PATH,
    )
    export_parser = subparsers.add_parser("export-reviews")
    export_parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    export_parser.add_argument("--comparison-run-id", required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "manifest":
        print(
            json.dumps(
                question_set_manifest(_questions_for_scope(args.scope)),
                ensure_ascii=False,
                indent=2,
            )
        )
    elif args.command == "prepare-request":
        _write_json(
            args.output,
            build_external_arm_request(
                args.arm,
                questions=_questions_for_scope(args.scope),
                evaluation_window_id=args.window_id,
            ),
        )
    elif args.command == "import-external":
        _write_json(
            args.output,
            build_external_arm_report(
                args.arm,
                _read_jsonl(args.responses),
                model=args.model,
                evaluated_at=args.evaluated_at,
                evaluation_window_id=args.window_id,
                questions=_questions_for_scope(args.scope),
            ),
        )
    elif args.command == "run-external":
        from adc_evidence.evaluation.external_arms import (
            run_siliconflow_external_arm,
        )

        _write_json(
            args.output,
            run_siliconflow_external_arm(
                args.arm,
                questions=_questions_for_scope(args.scope),
                evaluation_window_id=args.window_id,
            ),
        )
    elif args.command == "run-system":
        _write_json(
            args.output,
            run_adc_evidence_arm(
                database_path=args.database,
                questions=_questions_for_scope(args.scope),
                evaluation_window_id=args.window_id,
            ),
        )
    elif args.command == "run-offline-baseline":
        _write_json(
            args.output,
            run_offline_rag_baseline(
                database_path=args.database,
                questions=_questions_for_scope(args.scope),
                evaluation_window_id=args.window_id,
            ),
        )
    elif args.command == "compare-offline":
        from adc_evidence.evaluation.offline_comparison import compare_offline_reports

        questions = _questions_for_scope(args.scope)
        system_report = json.loads(args.system_report.read_text(encoding="utf-8"))
        baseline_report = json.loads(args.baseline_report.read_text(encoding="utf-8"))
        _write_json(args.output, compare_offline_reports(system_report, baseline_report, questions))
    elif args.command == "assemble":
        reports = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (args.direct_report, args.web_report, args.system_report)
        ]
        packet, identity_map = build_blinded_review_packet(
            reports,
            questions=_questions_for_scope(args.scope),
        )
        _write_json(args.packet, packet)
        _write_json(args.identity_map, identity_map)
        _write_json(
            BENCHMARK_REPORT_PATH,
            {
                "schema_version": BENCHMARK_SCHEMA_VERSION,
                "comparison_run_id": packet["comparison_run_id"],
                "evaluation_window_id": packet["evaluation_window_id"],
                "question_set_hash": packet["question_set_hash"],
                "question_count": packet["question_count"],
                "candidate_count": packet["candidate_count"],
                "status": "awaiting_blinded_human_review",
            },
        )
    elif args.command == "summarize":
        packet = json.loads(args.packet.read_text(encoding="utf-8"))
        identity_map = json.loads(args.identity_map.read_text(encoding="utf-8"))
        reviews = _read_jsonl(args.reviews)
        summary = aggregate_human_scores(packet, identity_map, reviews)
        bad_cases = build_benchmark_bad_case_report(packet, identity_map, reviews)
        regression = build_regression_candidates(packet, identity_map, reviews)
        _write_json(args.summary, summary)
        _write_json(args.bad_cases, bad_cases)
        _write_jsonl(args.regression_candidates, regression)
    else:
        from adc_evidence.review.repository import benchmark_reviews_from_database

        _write_jsonl(
            args.output,
            benchmark_reviews_from_database(
                args.comparison_run_id,
                args.database,
            ),
        )


if __name__ == "__main__":
    main()
