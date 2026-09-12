"""Build a content-free manifest for a human review JSONL export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.paper_readiness import build_human_review_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reviews", type=Path, help="Human paired-review JSONL")
    parser.add_argument("--review-set-version", required=True)
    parser.add_argument("--evaluation-window-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_human_review_manifest(
        args.reviews,
        review_set_version=args.review_set_version,
        evaluation_window_id=args.evaluation_window_id,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("review_file_sha256", "question_id_sha256", "question_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
