from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from adc_evidence.config import EVALUATION_PATH, GENERATION_QUESTIONS_PATH
from adc_evidence.generation.generators import create_generator
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.processing.normalize import normalize_text


def load_generation_questions(
    path: Path = GENERATION_QUESTIONS_PATH,
) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _safe_ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _aggregate_review_status(questions: list[dict[str, object]]) -> str:
    statuses = {
        str(question.get("review_status") or "unreviewed")
        for question in questions
    }
    return next(iter(statuses)) if len(statuses) == 1 else "mixed"


def new_generation_run_id(now: datetime | None = None) -> str:
    timestamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"gen-{timestamp}-{uuid4().hex[:8]}"


def evaluate_generation(
    *,
    backend: str = "extractive",
    retrieval_mode: str = "sparse",
    top_k: int = 5,
    questions_path: Path = GENERATION_QUESTIONS_PATH,
    run_id: str | None = None,
) -> dict[str, object]:
    questions = load_generation_questions(questions_path)
    generator = create_generator(backend)
    service = EvidenceAnsweringService(generator=generator)
    evaluated_at = datetime.now(timezone.utc)
    resolved_run_id = run_id or new_generation_run_id(evaluated_at)
    rows: list[dict[str, object]] = []

    expected_refusals = 0
    predicted_refusals = 0
    correct_refusals = 0
    answerable_count = 0
    answered_count = 0
    valid_citation_count = 0
    gold_citation_hit_count = 0
    grounded_success_count = 0
    key_fact_scores: list[float] = []
    total_latency_ms = 0
    error_count = 0
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    api_call_count = 0
    observed_models: set[str] = set()

    for item in questions:
        result = service.answer(
            str(item["question"]),
            retrieval_mode=retrieval_mode,
            top_k=top_k,
        )
        total_latency_ms += result.latency_ms
        if backend not in {"openai", "siliconflow"} or result.response_id is not None:
            observed_models.add(result.model)
        for token_name in total_usage:
            total_usage[token_name] += int(result.usage.get(token_name, 0))
        api_call_count += int(result.response_id is not None)
        should_refuse = bool(item["should_refuse"])
        predicted_refusal = result.status == "refused"
        expected_documents = set(str(value) for value in item["expected_document_ids"])
        cited_documents = {citation.retrieval_document_id for citation in result.citations}
        gold_hit = bool(expected_documents & cited_documents)
        citation_valid = bool(result.validation and result.validation.valid)

        required_terms = [str(value) for value in item.get("required_terms", [])]
        normalized_answer = normalize_text(result.answer).replace(" ", "")
        key_fact_recall = _safe_ratio(
            sum(
                normalize_text(term).replace(" ", "") in normalized_answer
                for term in required_terms
            ),
            len(required_terms),
        )

        if should_refuse:
            expected_refusals += 1
            correct_refusals += int(predicted_refusal)
        else:
            answerable_count += 1
            answered_count += int(result.status == "answered")
            valid_citation_count += int(citation_valid)
            gold_citation_hit_count += int(gold_hit)
            grounded_success_count += int(
                result.status == "answered" and citation_valid and gold_hit
            )
            key_fact_scores.append(key_fact_recall)
        predicted_refusals += int(predicted_refusal)
        error_count += int(result.status == "error")

        rows.append(
            {
                "question_id": item["question_id"],
                "category": item["category"],
                "question": item["question"],
                "question_review_status": item.get("review_status", "unreviewed"),
                "should_refuse": should_refuse,
                "status": result.status,
                "refusal_reason": result.refusal_reason,
                "expected_document_ids": sorted(expected_documents),
                "cited_document_ids": sorted(cited_documents),
                "citation_valid": citation_valid,
                "gold_citation_hit": gold_hit,
                "key_fact_recall": key_fact_recall,
                "latency_ms": result.latency_ms,
                "generator_backend": result.generator_backend,
                "model": result.model,
                "usage": result.usage,
                "response_id": result.response_id,
                "answer": result.answer,
            }
        )

    false_refusals = predicted_refusals - correct_refusals
    metrics = {
        "answer_success_rate": _safe_ratio(answered_count, answerable_count),
        "refusal_precision": _safe_ratio(correct_refusals, predicted_refusals),
        "refusal_recall": _safe_ratio(correct_refusals, expected_refusals),
        "false_refusal_rate": _safe_ratio(false_refusals, answerable_count),
        "citation_validity_rate": _safe_ratio(valid_citation_count, answered_count),
        "gold_citation_hit_rate": _safe_ratio(gold_citation_hit_count, answerable_count),
        "grounded_answer_rate": _safe_ratio(grounded_success_count, answerable_count),
        "key_fact_recall": round(sum(key_fact_scores) / len(key_fact_scores), 4)
        if key_fact_scores
        else 0.0,
        "error_rate": _safe_ratio(error_count, len(questions)),
        "average_latency_ms": round(total_latency_ms / len(questions)) if questions else 0,
        "api_call_count": api_call_count,
        "token_usage": total_usage,
    }
    return {
        "run_id": resolved_run_id,
        "evaluated_at": evaluated_at.isoformat(),
        "question_set": str(questions_path),
        "review_status": _aggregate_review_status(questions),
        "backend": backend,
        "requested_model": generator.model_name,
        "observed_models": sorted(observed_models),
        "retrieval_mode": retrieval_mode,
        "top_k": top_k,
        "question_count": len(questions),
        "answerable_count": answerable_count,
        "expected_refusal_count": expected_refusals,
        "metrics": metrics,
        "questions": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate cited answer generation.")
    parser.add_argument(
        "--backend",
        choices=("extractive", "siliconflow", "openai"),
        default="extractive",
    )
    parser.add_argument(
        "--retrieval-mode", choices=("sparse", "dense", "hybrid"), default="sparse"
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument(
        "--run-id",
        help="Optional stable identifier. Omit to generate a unique evaluation run ID.",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=GENERATION_QUESTIONS_PATH,
        help="JSONL question set. Defaults to the full generation evaluation set.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=EVALUATION_PATH / "generation_report.json",
    )
    args = parser.parse_args()
    report = evaluate_generation(
        backend=args.backend,
        retrieval_mode=args.retrieval_mode,
        top_k=args.top_k,
        questions_path=args.questions,
        run_id=args.run_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "run_id": report["run_id"],
                "backend": report["backend"],
                "requested_model": report["requested_model"],
                "observed_models": report["observed_models"],
                "metrics": report["metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
