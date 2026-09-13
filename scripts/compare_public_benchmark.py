"""Compare two paired reports on the public benchmark."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.public_benchmark import (
    compare_public_benchmark_reports,
    load_public_benchmark,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--system-report", type=Path, required=True)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    system = json.loads(args.system_report.read_text(encoding="utf-8-sig"))
    baseline = json.loads(args.baseline_report.read_text(encoding="utf-8-sig"))
    comparison = compare_public_benchmark_reports(
        system.get("questions", []), baseline.get("questions", []), load_public_benchmark(args.questions)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
