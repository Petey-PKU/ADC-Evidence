"""Fail closed if tracked public files contain common secret or local-path patterns."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adc_evidence.evaluation.public_hygiene import scan_tracked_public_files


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    report = scan_tracked_public_files(args.repo_root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["status"] == "clean" else 1)


if __name__ == "__main__":
    main()
