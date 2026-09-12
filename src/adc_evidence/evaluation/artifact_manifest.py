from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.evaluation.public_hygiene import scan_tracked_public_files


def build_public_artifact_manifest(repo_root: Path) -> dict[str, object]:
    """Build a public-only hash inventory for a reproducibility artifact."""
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, check=True, capture_output=True, text=True
    ).stdout.strip()
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo_root, check=True, capture_output=True
    ).stdout.decode().split("\0")
    files: list[dict[str, object]] = []
    for relative in sorted(item for item in listed if item):
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        raw = path.read_bytes()
        files.append(
            {
                "path": relative.replace("\\", "/"),
                "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "size_bytes": len(raw),
            }
        )
    hygiene = scan_tracked_public_files(repo_root)
    findings = hygiene.get("findings", [])
    finding_count = len(findings) if isinstance(findings, list) else 0
    return {
        "schema_version": "v0.6-public-artifact-manifest-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "code_commit": commit,
        "tracked_file_count": len(files),
        "files": files,
        "public_hygiene": {
            "status": hygiene["status"],
            "scanned_file_count": hygiene["scanned_file_count"],
            "finding_count": finding_count,
        },
        "privacy_note": "Only Git-tracked public paths and hashes are included; no file contents or identities.",
    }
