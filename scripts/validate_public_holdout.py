from __future__ import annotations

import json
import csv
from pathlib import Path

from adc_evidence.evaluation.benchmark import load_benchmark_questions
from adc_evidence.evaluation.holdout import (
    load_holdout_questions,
    validate_holdout_disjoint,
    validate_holdout_entity_mentions,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    holdout = load_holdout_questions(
        PROJECT_ROOT / "data" / "annotations" / "v0.6_public_holdout_questions.jsonl"
    )
    exposed = load_benchmark_questions()
    catalog_path = PROJECT_ROOT / "data" / "public" / "marketed_adc_catalog.csv"
    with catalog_path.open(encoding="utf-8-sig", newline="") as handle:
        catalog = list(csv.DictReader(handle))
    report = validate_holdout_disjoint(holdout, exposed)
    report["entity_bindings"] = validate_holdout_entity_mentions(holdout, catalog)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
