from __future__ import annotations

import argparse
from pathlib import Path

from adc_evidence.config import DEFAULT_DATABASE_PATH, DEFAULT_SEED_PATH
from adc_evidence.workbench import sync_public_seed_facts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize the ADC-Evidence database.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = sync_public_seed_facts(args.database, args.seed)
    print(
        f"Initialized {args.database} with {summary['adc_count']} ADC records "
        f"and {summary['facts_created']} new temporal facts."
    )


if __name__ == "__main__":
    main()
