from __future__ import annotations

import json
from pathlib import Path

from adc_evidence.evaluation.benchmark import load_benchmark_questions
from adc_evidence.evaluation.holdout import (
    load_holdout_questions,
    validate_holdout_disjoint,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    holdout = load_holdout_questions(
        PROJECT_ROOT / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
    )
    exposed = load_benchmark_questions()
    print(json.dumps(validate_holdout_disjoint(holdout, exposed), ensure_ascii=False))


if __name__ == "__main__":
    main()
