from __future__ import annotations

import argparse
from pathlib import Path

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    DEFAULT_SEED_PATH,
    environment_flag,
)
from adc_evidence.workbench import sync_public_seed_facts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize the ADC-Evidence database.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if (
        args.database.resolve() == DEFAULT_DATABASE_PATH.resolve()
        and not environment_flag("ADC_BOOTSTRAP_DEMO", default=False)
    ):
        raise RuntimeError(
            "Refusing to seed the public snapshot path. Use an explicit "
            "development path such as data/processed/adc_demo.db, or set "
            "ADC_BOOTSTRAP_DEMO=true only for an isolated demo."
        )
    summary = sync_public_seed_facts(args.database, args.seed)
    print(
        f"Initialized {args.database} with {summary['adc_count']} ADC records "
        f"and {summary['facts_created']} new temporal facts."
    )


if __name__ == "__main__":
    main()
