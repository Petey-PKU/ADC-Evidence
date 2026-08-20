from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.config import DEFAULT_DATABASE_PATH


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(
    database_path: Path = DEFAULT_DATABASE_PATH,
    output_directory: Path = Path("/app/backups"),
    *,
    timestamp: datetime | None = None,
) -> dict[str, object]:
    """Create a transaction-consistent SQLite backup and checksum manifest."""
    if not database_path.is_file():
        raise FileNotFoundError(f"Database not found: {database_path}")

    created_at = timestamp or datetime.now(UTC)
    stamp = created_at.strftime("%Y%m%dT%H%M%SZ")
    output_directory.mkdir(parents=True, exist_ok=True)
    backup_path = output_directory / f"adc_evidence-{stamp}.db"
    manifest_path = output_directory / f"adc_evidence-{stamp}.json"

    with closing(sqlite3.connect(database_path)) as source:
        with closing(sqlite3.connect(backup_path)) as destination:
            source.backup(destination)

    manifest: dict[str, object] = {
        "created_at": created_at.isoformat(),
        "database": backup_path.name,
        "size_bytes": backup_path.stat().st_size,
        "sha256": sha256_file(backup_path),
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {**manifest, "backup_path": str(backup_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the ADC-Evidence SQLite DB.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--output-dir", type=Path, default=Path("/app/backups"))
    args = parser.parse_args()
    print(
        json.dumps(
            backup_database(args.database, args.output_dir), ensure_ascii=False
        )
    )


if __name__ == "__main__":
    main()
