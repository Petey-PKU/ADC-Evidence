"""Freeze integrity metadata for a confirmation holdout kept outside the repo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.paper_readiness import build_independent_holdout_manifest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--question-set-version", required=True)
    parser.add_argument("--evaluation-window-id", required=True)
    parser.add_argument("--access-control-method", required=True)
    parser.add_argument("--database-data-version")
    parser.add_argument("--code-commit")
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    questions = args.questions.resolve()
    repo_root = args.repo_root.resolve()
    if questions == repo_root or repo_root in questions.parents:
        raise ValueError("Independent holdout questions must be stored outside the public repository")
    manifest = build_independent_holdout_manifest(
        questions,
        question_set_version=args.question_set_version,
        evaluation_window_id=args.evaluation_window_id,
        access_control_method=args.access_control_method,
        database_data_version=args.database_data_version,
        code_commit=args.code_commit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("question_file_sha256", "question_set_hash", "question_count")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
