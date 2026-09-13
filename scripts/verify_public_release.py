"""Verify checksums and layout of an ADC-Evidence public release archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import zipfile
from pathlib import PurePosixPath
from pathlib import Path


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _database_absolute_path_count(payload: bytes) -> int:
    """Count machine-specific paths in path-bearing SQLite text columns."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(payload)
        pattern = re.compile(r"(?:[A-Za-z]:[\\/]|/Users/|/home/|\\\\)")
        count = 0
        tables = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        for table in tables:
            quoted_table = '"' + table.replace('"', '""') + '"'
            columns = [
                (str(row[1]), str(row[2]).upper())
                for row in connection.execute(f"PRAGMA table_info({quoted_table})").fetchall()
                if "TEXT" in str(row[2]).upper()
                and ("path" in str(row[1]).casefold() or str(row[1]).casefold() == "parameters_json")
            ]
            for column, _ in columns:
                quoted_column = '"' + column.replace('"', '""') + '"'
                for value, in connection.execute(f"SELECT {quoted_column} FROM {quoted_table} WHERE {quoted_column} IS NOT NULL"):
                    count += int(pattern.search(str(value)) is not None)
        return count
    finally:
        connection.close()


def verify_release(path: Path) -> dict[str, object]:
    """Return a machine-readable verification report or raise on failure."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"release archive not found: {path}")
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "RELEASE_MANIFEST.json" not in names:
            raise ValueError("release is missing RELEASE_MANIFEST.json")
        try:
            manifest = json.loads(archive.read("RELEASE_MANIFEST.json"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("release manifest is not valid UTF-8 JSON") from exc
        if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), list):
            raise ValueError("release manifest must contain a files list")

        checked: list[str] = []
        seen: set[str] = set()
        database_absolute_path_count = 0
        for entry in manifest["files"]:
            if not isinstance(entry, dict):
                raise ValueError("release manifest contains a non-object file entry")
            archive_path = str(entry.get("archive_path", ""))
            if not archive_path or archive_path in seen:
                raise ValueError(f"duplicate or empty archive path: {archive_path!r}")
            seen.add(archive_path)
            pure = PurePosixPath(archive_path)
            if pure.is_absolute() or ".." in pure.parts:
                raise ValueError(f"unsafe archive path: {archive_path}")
            if archive_path not in names:
                raise ValueError(f"manifest file is missing from archive: {archive_path}")
            payload = archive.read(archive_path)
            expected_size = entry.get("size_bytes")
            if expected_size != len(payload):
                raise ValueError(f"size mismatch for {archive_path}")
            expected_hash = str(entry.get("sha256", ""))
            if expected_hash != _sha256(payload):
                raise ValueError(f"checksum mismatch for {archive_path}")
            if archive_path.startswith("data/processed/") and archive_path.endswith(".db"):
                database_absolute_path_count = _database_absolute_path_count(payload)
                if database_absolute_path_count:
                    raise ValueError(
                        f"database contains {database_absolute_path_count} absolute local paths"
                    )
            checked.append(archive_path)
        allowed_names = seen | {"RELEASE_MANIFEST.json", "RELEASE_README.md"}
        unexpected = sorted(names - allowed_names)
        if unexpected:
            raise ValueError(f"archive contains unlisted files: {unexpected}")
        if "RELEASE_README.md" not in names:
            raise ValueError("release is missing RELEASE_README.md")

        return {
            "status": "verified",
            "archive": str(path),
            "dataset_as_of": manifest.get("dataset_as_of"),
            "retrieval_corpus_version": manifest.get("retrieval_corpus_version"),
            "checked_file_count": len(checked),
            "database_absolute_path_count": database_absolute_path_count,
            "benchmark_question_file_present": "data/annotations/public_benchmark_v1.jsonl" in names,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_release(args.archive), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
