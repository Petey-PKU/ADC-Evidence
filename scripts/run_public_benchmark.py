"""Run the public benchmark with the deterministic offline answer path."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.evaluation.public_benchmark import (
    load_public_benchmark,
    score_public_benchmark,
)
from adc_evidence.evaluation.public_benchmark import _sha256 as _object_hash
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.workbench import evidence_data_version


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = ROOT / "data" / "annotations" / "public_benchmark_v1.jsonl"
DEFAULT_DATABASE = ROOT / "data" / "processed" / "adc_public_2026-09-30.db"
DEFAULT_INDEX = ROOT / "artifacts" / "vector_index" / "public_2026-09-30"
DEFAULT_SEED = ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_OUTPUT = ROOT / "artifacts" / "evaluation" / "public_benchmark_v1_report.json"


def run(args: argparse.Namespace) -> dict[str, object]:
    questions = load_public_benchmark(args.questions)
    retriever = HybridRetriever(
        database_path=args.database,
        index_path=args.index_path,
        seed_path=args.seed,
    )
    service = EvidenceAnsweringService(
        retriever=retriever,
        database_path=args.database,
        generator=ExtractiveGenerator(),
    )
    outputs: list[dict[str, object]] = []
    for question in questions:
        result = service.answer(str(question["question"]))
        source_ids = []
        for citation in result.citations:
            retrieval_id = str(citation.retrieval_document_id)
            source_ids.append(retrieval_id.split(":", 1)[-1])
        outputs.append({
            "question_id": question["question_id"],
            "route": result.route,
            "status": result.status,
            "refusal_reason": result.refusal_reason,
            "citation_source_record_ids": sorted(set(source_ids)),
            "citation_count": len(result.citations),
            "claim_count": len(result.claims),
            "latency_ms": result.latency_ms,
            "answer_hash": f"sha256:{_object_hash(result.answer)}",
        })
    scored = score_public_benchmark(outputs, questions)
    return {
        "schema_version": "public-adc-benchmark-report-v1",
        "benchmark_file": str(args.questions),
        "database_file": str(args.database),
        "index_path": str(args.index_path),
        "evaluated_at": datetime.now(UTC).isoformat(),
        "network_enabled": False,
        "model": "extractive-offline-v1",
        "database_data_version": evidence_data_version(args.database),
        "automatic_scoring": scored,
        "human_review": {"status": "pending", "required": True},
        "questions": outputs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["automatic_scoring"], ensure_ascii=False, indent=2))
    print(f"Report: {args.output}")


if __name__ == "__main__":
    main()
