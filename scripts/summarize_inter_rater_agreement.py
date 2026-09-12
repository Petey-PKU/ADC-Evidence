"""Summarize two independent human ratings per question from JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.human_review import (
    load_human_paired_reviews,
    summarize_inter_rater_agreement,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reviews", type=Path, help="Two-rater review JSONL")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--field", default="answer_verdict")
    args = parser.parse_args()
    summary = summarize_inter_rater_agreement(
        load_human_paired_reviews(args.reviews), field=args.field
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
