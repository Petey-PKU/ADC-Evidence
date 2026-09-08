from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.config import (
    BENCHMARK_REVIEW_PACKET_PATH,
    DEFAULT_DATABASE_PATH,
    GENERATION_REPORT_PATH,
    RETRIEVAL_REPORT_PATH,
)
from adc_evidence.review.repository import prepare_review_queue, review_stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import retrieval, generation and blinded benchmark evaluations into the review queue."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--generation-report", type=Path, default=GENERATION_REPORT_PATH)
    parser.add_argument("--retrieval-report", type=Path, default=RETRIEVAL_REPORT_PATH)
    parser.add_argument(
        "--benchmark-packet",
        type=Path,
        default=BENCHMARK_REVIEW_PACKET_PATH,
    )
    parser.add_argument(
        "--retrieval-mode",
        choices=("sparse", "dense", "hybrid"),
        default="sparse",
    )
    args = parser.parse_args()
    imported = prepare_review_queue(
        database_path=args.database,
        generation_report_path=args.generation_report,
        retrieval_report_path=args.retrieval_report,
        benchmark_packet_path=args.benchmark_packet,
        retrieval_mode=args.retrieval_mode,
    )
    print(
        json.dumps(
            {"imported": imported, "queue": review_stats(args.database)},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
