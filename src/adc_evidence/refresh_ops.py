from __future__ import annotations

import json
import os
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypeVar

from adc_evidence.database import connect, create_database


T = TypeVar("T")


def retry_call(
    operation: Callable[[], T],
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[T, int]:
    """Run a source operation with bounded exponential backoff."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if base_delay_seconds < 0:
        raise ValueError("base_delay_seconds cannot be negative")
    for attempt in range(1, max_attempts + 1):
        try:
            return operation(), attempt
        except Exception:
            if attempt == max_attempts:
                raise
            sleep(base_delay_seconds * (2 ** (attempt - 1)))
    raise AssertionError("unreachable")


class RefreshLock:
    """Cross-process lock based on exclusive file creation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "acquired_at": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        ).encode("utf-8")
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError as exc:
            owner = self.path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(
                f"Another refresh owns the lock {self.path}: {owner}"
            ) from exc
        try:
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)
        self._acquired = True

    def release(self) -> None:
        if self._acquired:
            self.path.unlink(missing_ok=True)
            self._acquired = False

    def __enter__(self) -> "RefreshLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


def _gate(
    name: str,
    passed: bool,
    *,
    blocking: bool = True,
    details: object = None,
) -> dict[str, object]:
    return {
        "name": name,
        "passed": passed,
        "blocking": blocking,
        "details": details,
    }


def evaluate_refresh_gates(
    database_path: Path,
    run_id: str,
    *,
    required_sources: tuple[str, ...],
    max_count_drop_ratio: float = 0.25,
    max_missing_records: int = 0,
) -> dict[str, object]:
    """Evaluate publication gates against a staged refresh database."""
    if not 0 <= max_count_drop_ratio < 1:
        raise ValueError("max_count_drop_ratio must be in [0, 1)")
    if max_missing_records < 0:
        raise ValueError("max_missing_records cannot be negative")
    create_database(database_path)
    checks: list[dict[str, object]] = []
    with closing(connect(database_path)) as connection:
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        checks.append(_gate("sqlite_integrity", integrity == "ok", details=integrity))
        checks.append(
            _gate(
                "foreign_keys",
                not foreign_keys,
                details=[tuple(row) for row in foreign_keys],
            )
        )
        ingestion_run = connection.execute(
            "SELECT status, error_text FROM ingestion_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        checks.append(
            _gate(
                "ingestion_run_status",
                ingestion_run is not None and str(ingestion_run["status"]) == "complete",
                details=(
                    {"status": "missing"}
                    if ingestion_run is None
                    else {
                        "status": str(ingestion_run["status"]),
                        "error": ingestion_run["error_text"],
                    }
                ),
            )
        )

        rows = connection.execute(
            """
            SELECT source, status, attempts, expected_count, collected_count,
                   is_complete, error_text, details_json
            FROM ingestion_source_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
        statuses = {str(row["source"]): row for row in rows}
        for source in required_sources:
            row = statuses.get(source)
            checks.append(
                _gate(
                    f"source_status:{source}",
                    row is not None and str(row["status"]) == "complete",
                    details=(
                        {"status": "missing"}
                        if row is None
                        else {
                            "status": row["status"],
                            "attempts": row["attempts"],
                            "expected_count": row["expected_count"],
                            "collected_count": row["collected_count"],
                            "is_complete": bool(row["is_complete"]),
                            "error": row["error_text"],
                        }
                    ),
                )
            )
            if row is None or str(row["status"]) != "complete":
                continue
            previous = connection.execute(
                """
                SELECT run_id, collected_count
                FROM ingestion_source_runs
                WHERE source = ? AND run_id <> ? AND status = 'complete'
                ORDER BY finished_at DESC, run_id DESC
                LIMIT 1
                """,
                (source, run_id),
            ).fetchone()
            current_count = int(row["collected_count"])
            if previous is None or int(previous["collected_count"]) == 0:
                checks.append(
                    _gate(
                        f"count_anomaly:{source}",
                        True,
                        details={"baseline": None, "current": current_count},
                    )
                )
            else:
                baseline = int(previous["collected_count"])
                ratio = current_count / baseline
                checks.append(
                    _gate(
                        f"count_anomaly:{source}",
                        ratio >= 1 - max_count_drop_ratio,
                        details={
                            "baseline_run_id": str(previous["run_id"]),
                            "baseline": baseline,
                            "current": current_count,
                            "ratio": round(ratio, 4),
                            "minimum_ratio": 1 - max_count_drop_ratio,
                        },
                    )
                )
            if not bool(row["is_complete"]):
                source_details = json.loads(str(row["details_json"]))
                planned = bool(source_details.get("planned_truncation"))
                checks.append(
                    _gate(
                        f"missing_detection_scope:{source}",
                        planned,
                        blocking=not planned,
                        details={
                            "full_source_snapshot": False,
                            "planned_truncation": planned,
                            "message": "missing-record detection disabled for this source run",
                        },
                    )
                )

        missing_rows = connection.execute(
            """
            SELECT event_id, source, source_record_id, details_json
            FROM change_events
            WHERE event_type = 'source.record_missing'
            """
        ).fetchall()
        current_missing = [
            {
                "event_id": str(row["event_id"]),
                "source": str(row["source"]),
                "source_record_id": str(row["source_record_id"]),
            }
            for row in missing_rows
            if json.loads(str(row["details_json"])).get("run_id") == run_id
        ]
        checks.append(
            _gate(
                "missing_records",
                len(current_missing) <= max_missing_records,
                details={
                    "count": len(current_missing),
                    "maximum": max_missing_records,
                    "records": current_missing,
                },
            )
        )

    passed = all(
        bool(check["passed"])
        for check in checks
        if bool(check["blocking"])
    )
    return {
        "run_id": run_id,
        "passed": passed,
        "thresholds": {
            "max_count_drop_ratio": max_count_drop_ratio,
            "max_missing_records": max_missing_records,
        },
        "checks": checks,
    }
