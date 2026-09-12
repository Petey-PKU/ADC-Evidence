from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from adc_evidence.evaluation.benchmark import _system_row, automatic_diagnostics
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.generation.service import EvidenceAnsweringService
from adc_evidence.rag.retriever import HybridRetriever
from adc_evidence.workbench import evidence_data_version


ABLATION_SCHEMA_VERSION = "v0.6-component-ablation-v1"


def _digest(questions: list[dict[str, object]]) -> str:
    payload = json.dumps(questions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _RankedOnlyRetriever:
    """Retriever adapter that intentionally omits exact identifier routing."""

    def __init__(self, database_path: Path) -> None:
        self.inner = HybridRetriever(database_path=database_path)

    def search(self, query: str, **kwargs):
        return self.inner.search(query, **kwargs)


def run_identifier_routing_ablation(
    *,
    database_path: Path,
    questions: list[dict[str, object]],
    evaluation_window_id: str,
    evaluated_at: str | None = None,
) -> dict[str, object]:
    """Compare exact PMID/NCT routing with ranked retrieval only."""
    evaluated_at = evaluated_at or datetime.now(UTC).isoformat()
    services = {
        "full_system": EvidenceAnsweringService(
            database_path=database_path,
            generator=ExtractiveGenerator(),
        ),
        "without_identifier_routing": EvidenceAnsweringService(
            database_path=database_path,
            retriever=_RankedOnlyRetriever(database_path),
            generator=ExtractiveGenerator(),
        ),
    }
    arms: dict[str, object] = {}
    for name, service in services.items():
        outputs = [_system_row(row, service.answer(str(row["question"]))) for row in questions]
        arms[name] = {
            "network_enabled": False,
            "model": "v0.6-structured-validator-v4",
            "automatic_diagnostics": automatic_diagnostics(outputs, questions),
            "questions": outputs,
        }
    full = {row["question_id"]: row for row in arms["full_system"]["questions"]}
    without = {
        row["question_id"]: row
        for row in arms["without_identifier_routing"]["questions"]
    }
    paired_status = Counter(
        (full[question_id]["status"], without[question_id]["status"])
        for question_id in full
    )
    paired_routes = Counter(
        (full[question_id].get("route"), without[question_id].get("route"))
        for question_id in full
    )
    changed_ids = sorted(
        question_id
        for question_id in full
        if (
            full[question_id]["status"], full[question_id].get("route")
        )
        != (
            without[question_id]["status"], without[question_id].get("route")
        )
    )
    return {
        "schema_version": ABLATION_SCHEMA_VERSION,
        "ablation_component": "exact_identifier_routing",
        "question_set_hash": f"sha256:{_digest(questions)}",
        "question_count": len(questions),
        "evaluation_window_id": evaluation_window_id,
        "evaluated_at": evaluated_at,
        "database_data_version": evidence_data_version(database_path),
        "network_enabled": False,
        "arms": arms,
        "paired_status_counts": {
            f"{full_status}->{without_status}": count
            for (full_status, without_status), count in sorted(paired_status.items())
        },
        "paired_route_counts": {
            f"{full_route}->{without_route}": count
            for (full_route, without_route), count in sorted(
                paired_routes.items(), key=lambda item: str(item[0])
            )
        },
        "changed_question_ids": changed_ids,
        "interpretation": "Component-level engineering comparison only; semantic correctness needs review labels.",
    }
