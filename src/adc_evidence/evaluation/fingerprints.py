"""Stable fingerprints used to bind automated evaluation artifacts."""

from __future__ import annotations

import hashlib
from typing import Iterable


def question_id_sha256(question_ids: Iterable[str]) -> str:
    """Return a content-free binding for a question set."""
    canonical = "\n".join(sorted(str(item) for item in question_ids))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
