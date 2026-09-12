"""Build a public-only reproducibility hash manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.artifact_manifest import build_public_artifact_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_public_artifact_manifest(args.repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"code_commit": report["code_commit"], "tracked_file_count": report["tracked_file_count"], "hygiene": report["public_hygiene"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
