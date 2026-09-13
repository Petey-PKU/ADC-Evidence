"""Validate that a public benchmark manifest binds its question file."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from adc_evidence.evaluation.public_benchmark import _canonical, load_public_benchmark


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def validate_public_benchmark(
    questions_path: Path,
    manifest_path: Path,
    *,
    catalog_path: Path | None = None,
) -> dict[str, object]:
    questions_path = questions_path.resolve()
    manifest_path = manifest_path.resolve()
    rows = load_public_benchmark(questions_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict):
        raise ValueError("Benchmark manifest must be a JSON object")
    question_bytes = questions_path.read_bytes()
    expected_file_hash = str(manifest.get("question_file_sha256", ""))
    actual_file_hash = _sha256_bytes(question_bytes)
    if expected_file_hash != actual_file_hash:
        raise ValueError("question_file_sha256 does not match question file")
    actual_set_hash = _sha256_bytes(
        _canonical(rows).encode("utf-8")
    )
    if manifest.get("question_set_sha256") != actual_set_hash:
        raise ValueError("question_set_sha256 does not match question rows")
    if manifest.get("question_count") != len(rows):
        raise ValueError("question_count does not match question file")
    split_counts = dict(sorted(Counter(str(row["split"]) for row in rows).items()))
    category_counts = dict(sorted(Counter(str(row["category"]) for row in rows).items()))
    if manifest.get("split_counts") != split_counts:
        raise ValueError("split_counts does not match question file")
    if manifest.get("category_counts") != category_counts:
        raise ValueError("category_counts does not match question file")
    catalog_hash = None
    if catalog_path is not None:
        catalog_hash = _sha256_bytes(catalog_path.resolve().read_bytes())
        if manifest.get("catalog_sha256") != catalog_hash:
            raise ValueError("catalog_sha256 does not match catalog file")
    return {
        "status": "verified",
        "question_count": len(rows),
        "question_file_sha256": actual_file_hash,
        "question_set_sha256": actual_set_hash,
        "catalog_sha256": catalog_hash or manifest.get("catalog_sha256"),
        "split_counts": split_counts,
        "category_counts": category_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_public_benchmark(args.questions, args.manifest, catalog_path=args.catalog), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
