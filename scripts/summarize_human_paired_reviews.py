"""Summarize a JSONL file of explicitly human paired review labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.human_review import (
    load_human_paired_reviews,
    summarize_human_paired_reviews,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reviews", type=Path, help="Human paired-review JSONL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    summary = summarize_human_paired_reviews(
        load_human_paired_reviews(args.reviews),
        bootstrap_iterations=args.bootstrap_iterations,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
