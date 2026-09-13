from __future__ import annotations

import shutil
from pathlib import Path
from uuid import uuid4


_WORKSPACE_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test_tmp"


class WorkspaceTemporaryDirectory:
    """Temporary directory that avoids restricted system-temp ACL operations."""

    def __init__(self) -> None:
        _WORKSPACE_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.name = str(_WORKSPACE_TEMP_ROOT / f"tmp-{uuid4().hex}")
        Path(self.name).mkdir()

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, *_: object) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        shutil.rmtree(self.name, ignore_errors=True)
