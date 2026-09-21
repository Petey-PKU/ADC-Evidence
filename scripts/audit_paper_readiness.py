"""Run the fail-closed public paper-readiness audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.paper_readiness import audit_public_paper_readiness


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--human-review-jsonl", type=Path)
    parser.add_argument("--human-review-manifest", type=Path)
    parser.add_argument("--independent-holdout-manifest", type=Path)
    parser.add_argument("--independent-holdout-questions", type=Path)
    parser.add_argument("--public-dataset-audit", type=Path)
    parser.add_argument("--public-catalog-source-audit", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit_public_paper_readiness(
        args.repo_root,
        human_review_jsonl=args.human_review_jsonl,
        human_review_manifest=args.human_review_manifest,
        independent_holdout_manifest=args.independent_holdout_manifest,
        independent_holdout_questions=args.independent_holdout_questions,
        public_dataset_audit=args.public_dataset_audit,
        public_catalog_source_audit=args.public_catalog_source_audit,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if report["status"] == "evidence_ready_for_submission_review" else 2)


if __name__ == "__main__":
    main()
