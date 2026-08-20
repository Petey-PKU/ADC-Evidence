from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from adc_evidence.config import (
    DEFAULT_DATABASE_PATH,
    REVIEW_EXPORT_CSV_PATH,
    REVIEW_EXPORT_JSONL_PATH,
    REVIEW_EXPORT_MANIFEST_PATH,
)
from adc_evidence.review.repository import review_export_rows, review_stats


EXPORT_SCHEMA_VERSION = "1.0"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return "" if value is None else value


def export_reviews(
    *,
    database_path: Path = DEFAULT_DATABASE_PATH,
    jsonl_path: Path = REVIEW_EXPORT_JSONL_PATH,
    csv_path: Path = REVIEW_EXPORT_CSV_PATH,
    manifest_path: Path = REVIEW_EXPORT_MANIFEST_PATH,
) -> dict[str, object]:
    rows = review_export_rows(database_path)
    exported_at = datetime.now(timezone.utc).isoformat()
    export_rows = [
        {
            "export_schema_version": EXPORT_SCHEMA_VERSION,
            "exported_at": exported_at,
            **row,
        }
        for row in rows
    ]
    jsonl_text = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in export_rows
    )
    _atomic_write(jsonl_path, jsonl_text)

    fieldnames = sorted({key for row in export_rows for key in row})
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_temporary = csv_path.with_suffix(csv_path.suffix + ".tmp")
    with csv_temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(
            {key: _csv_value(value) for key, value in row.items()}
            for row in export_rows
        )
    csv_temporary.replace(csv_path)

    reviewed_rows = sum(row.get("review_id") is not None for row in rows)
    manifest: dict[str, object] = {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": exported_at,
        "source_database": str(database_path),
        "unique_item_count": len({str(row["item_id"]) for row in rows}),
        "export_row_count": len(rows),
        "review_record_count": reviewed_rows,
        "pending_item_count": sum(row["review_status"] == "pending" for row in rows),
        "queue_stats": review_stats(database_path),
        "files": {
            "jsonl": {"path": str(jsonl_path), "sha256": _sha256(jsonl_path)},
            "csv": {"path": str(csv_path), "sha256": _sha256(csv_path)},
        },
    }
    _atomic_write(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export review items and human judgments to JSONL and CSV."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--jsonl", type=Path, default=REVIEW_EXPORT_JSONL_PATH)
    parser.add_argument("--csv", type=Path, default=REVIEW_EXPORT_CSV_PATH)
    parser.add_argument("--manifest", type=Path, default=REVIEW_EXPORT_MANIFEST_PATH)
    args = parser.parse_args()
    manifest = export_reviews(
        database_path=args.database,
        jsonl_path=args.jsonl,
        csv_path=args.csv,
        manifest_path=args.manifest,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

