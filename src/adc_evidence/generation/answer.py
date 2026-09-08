from __future__ import annotations

import argparse
from pathlib import Path

from adc_evidence.config import DEFAULT_DATABASE_PATH
from adc_evidence.generation.generators import create_generator
from adc_evidence.generation.service import EvidenceAnsweringService


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a cited ADC-Evidence answer.")
    parser.add_argument("question")
    parser.add_argument(
        "--backend",
        choices=("auto", "extractive", "siliconflow", "openai"),
        default="auto",
    )
    parser.add_argument(
        "--retrieval-mode", choices=("sparse", "dense", "hybrid"), default="sparse"
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    args = parser.parse_args()
    service = EvidenceAnsweringService(
        database_path=args.database,
        generator=create_generator(args.backend),
    )
    result = service.answer(
        args.question,
        retrieval_mode=args.retrieval_mode,
        top_k=args.top_k,
    )
    print(result.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
