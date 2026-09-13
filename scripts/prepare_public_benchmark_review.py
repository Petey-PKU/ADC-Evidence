"""Prepare a human-review packet from the public benchmark and a run report.

The packet contains no private data and leaves every verdict blank. It is a
review aid, not a substitute for independent human labels.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from adc_evidence.evaluation.public_benchmark import load_public_benchmark


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTIONS = ROOT / "data" / "annotations" / "public_benchmark_v1.jsonl"
DEFAULT_REPORT = ROOT / "artifacts" / "evaluation" / "public_benchmark_v1_report.json"


def _hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_packet(questions_path: Path, report_path: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    questions = load_public_benchmark(questions_path)
    report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    observed = {str(row.get("question_id")): row for row in report.get("questions", [])}
    if set(observed) != {str(row["question_id"]) for row in questions}:
        raise ValueError("System report question IDs must exactly match the benchmark")
    packet = []
    for question in questions:
        output = observed[str(question["question_id"])]
        packet.append({
            "question_id": question["question_id"],
            "split": question["split"],
            "category": question["category"],
            "question": question["question"],
            "expected_route": question["expected_route"],
            "expected_status": question["expected_status"],
            "standard_answer": question["standard_answer"],
            "allowed_answers": question["allowed_answers"],
            "evidence_sources": question["evidence_sources"],
            "allow_partial": question["allow_partial"],
            "should_refuse": question["should_refuse"],
            "system_output": {
                "route": output.get("route"),
                "status": output.get("status"),
                "answer": output.get("answer"),
                "refusal_reason": output.get("refusal_reason"),
                "claims": output.get("claims", []),
                "citation_source_record_ids": output.get("citation_source_record_ids", []),
            },
            "review": {
                "status": "pending",
                "reviewer_slot": None,
                "review_origin": None,
                "answer_verdict": None,
                "evidence_verdict": None,
                "citation_verdict": None,
                "completeness_verdict": None,
                "refusal_verdict": None,
                "notes": None,
            },
        })
    manifest = {
        "schema_version": "public-adc-benchmark-review-packet-v1",
        "benchmark_file_sha256": _hash(questions_path),
        "system_report_sha256": _hash(report_path),
        "question_count": len(packet),
        "status": "awaiting_independent_human_review",
        "review_instructions": "Use two independent reviewers; fill verdicts and review_origin=human_independent. Resolve disagreements with a separate adjudicator record.",
        "ai_assisted_labels_accepted": False,
    }
    return packet, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS)
    parser.add_argument("--system-report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    packet, manifest = prepare_packet(args.questions, args.system_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in packet),
        encoding="utf-8",
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
