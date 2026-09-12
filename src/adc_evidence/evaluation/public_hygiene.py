from __future__ import annotations

import re
import subprocess
from pathlib import Path


_SENSITIVE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key", re.compile(r"(?i)(?:sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_-]{20,})")),
    ("bearer_token", re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{24,}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("local_path", re.compile(r"(?i)(?:[A-Z]:\\Users\\|/home/[A-Za-z0-9_.-]+/)")),
)


def scan_public_text(path: str, text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for kind, pattern in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            findings.append({"path": path, "kind": kind})
    return findings


def scan_tracked_public_files(repo_root: Path) -> dict[str, object]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo_root, check=True, capture_output=True
    )
    paths = [Path(item) for item in result.stdout.decode().split("\0") if item]
    findings: list[dict[str, str]] = []
    for path in paths:
        absolute = repo_root / path
        if absolute.is_file():
            findings.extend(scan_public_text(path.as_posix(), absolute.read_text(encoding="utf-8", errors="ignore")))
    return {
        "schema_version": "v0.6-public-hygiene-v1",
        "status": "clean" if not findings else "findings",
        "scanned_file_count": len(paths),
        "findings": findings,
        "method": "tracked UTF-8 text scan; reports file/category only",
    }
