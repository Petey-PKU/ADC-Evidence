from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from adc_evidence.config import EVALUATION_PATH, RETRIEVAL_QUESTIONS_PATH
from adc_evidence.rag.retriever import HybridRetriever


def load_questions(path: Path = RETRIEVAL_QUESTIONS_PATH) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def _aggregate_review_status(questions: list[dict[str, object]]) -> str:
    statuses = {
        str(question.get("review_status") or "unreviewed")
        for question in questions
    }
    return next(iter(statuses)) if len(statuses) == 1 else "mixed"


def _question_metrics(retrieved: list[str], relevant: set[str], max_k: int) -> dict[str, float]:
    first_rank = next(
        (rank for rank, document_id in enumerate(retrieved[:max_k], start=1) if document_id in relevant),
        None,
    )
    gains = [1.0 if document_id in relevant else 0.0 for document_id in retrieved[:max_k]]
    dcg = sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
    ideal_count = min(len(relevant), max_k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return {
        "reciprocal_rank": 1.0 / first_rank if first_rank else 0.0,
        "ndcg": dcg / idcg if idcg else 0.0,
        **{
            f"hit_at_{k}": float(any(item in relevant for item in retrieved[:k]))
            for k in (1, 3, 5, 10)
            if k <= max_k
        },
    }


def evaluate_mode(
    retriever: HybridRetriever,
    questions: list[dict[str, object]],
    mode: str,
    *,
    top_k: int = 10,
    sparse_weight: float = 6.0,
    dense_weight: float = 1.0,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    totals: defaultdict[str, float] = defaultdict(float)
    category_totals: dict[str, defaultdict[str, float]] = defaultdict(lambda: defaultdict(float))
    category_counts: defaultdict[str, int] = defaultdict(int)

    for question in questions:
        search_options: dict[str, object] = {"top_k": top_k}
        if mode == "hybrid":
            search_options.update(
                sparse_weight=sparse_weight,
                dense_weight=dense_weight,
            )
        results = retriever.search(str(question["question"]), mode=mode, **search_options)
        retrieved = list(dict.fromkeys(item.retrieval_document_id for item in results))
        relevant = set(str(item) for item in question["expected_document_ids"])
        metrics = _question_metrics(retrieved, relevant, top_k)
        category = str(question["category"])
        category_counts[category] += 1
        for name, value in metrics.items():
            totals[name] += value
            category_totals[category][name] += value
        rows.append(
            {
                "question_id": question["question_id"],
                "category": category,
                "question": question["question"],
                "question_review_status": question.get("review_status", "unreviewed"),
                "expected_document_ids": sorted(relevant),
                "retrieved_document_ids": retrieved,
                **metrics,
            }
        )

    count = len(questions)
    return {
        "mode": mode,
        "sparse_weight": sparse_weight if mode == "hybrid" else None,
        "dense_weight": dense_weight if mode == "hybrid" else None,
        "question_count": count,
        "metrics": {name: round(value / count, 4) for name, value in totals.items()},
        "metrics_by_category": {
            category: {
                name: round(value / category_counts[category], 4)
                for name, value in values.items()
            }
            for category, values in category_totals.items()
        },
        "questions": rows,
    }


def evaluate(
    modes: list[str],
    *,
    top_k: int = 10,
    questions_path: Path = RETRIEVAL_QUESTIONS_PATH,
    sparse_weight: float = 6.0,
    dense_weight: float = 1.0,
    run_id: str | None = None,
) -> dict[str, object]:
    questions = load_questions(questions_path)
    retriever = HybridRetriever()
    results = [
        evaluate_mode(
            retriever,
            questions,
            mode,
            top_k=top_k,
            sparse_weight=sparse_weight,
            dense_weight=dense_weight,
        )
        for mode in modes
    ]
    evaluated_at = datetime.now(timezone.utc)
    resolved_run_id = run_id or (
        f"ret-{evaluated_at.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
    )
    return {
        "run_id": resolved_run_id,
        "evaluated_at": evaluated_at.isoformat(),
        "question_set": str(questions_path),
        "review_status": _aggregate_review_status(questions),
        "top_k": top_k,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate ADC-Evidence retrieval.")
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=("sparse", "dense", "hybrid"),
        default=["sparse", "dense", "hybrid"],
    )
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--sparse-weight", type=float, default=6.0)
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--run-id")
    parser.add_argument("--output", type=Path, default=EVALUATION_PATH / "retrieval_report.json")
    args = parser.parse_args()
    report = evaluate(
        args.modes,
        top_k=args.top_k,
        sparse_weight=args.sparse_weight,
        dense_weight=args.dense_weight,
        run_id=args.run_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        item["mode"]: item["metrics"]
        for item in report["results"]
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
