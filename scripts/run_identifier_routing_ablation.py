from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.ablation import run_identifier_routing_ablation
from adc_evidence.evaluation.holdout import load_holdout_questions


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the exact identifier-routing ablation.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_identifier_routing_ablation(
        database_path=args.database,
        questions=load_holdout_questions(args.questions),
        evaluation_window_id=args.window_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
