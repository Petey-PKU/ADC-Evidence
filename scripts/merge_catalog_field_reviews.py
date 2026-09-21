"""Pair two independent catalog field-review packets without choosing values."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:  # Works both as ``python -m scripts...`` and as a direct script path.
    from scripts.validate_catalog_field_review import validate_review_packet
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI smoke test
    from validate_catalog_field_review import validate_review_packet


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}: line {line_number} must be an object")
            rows.append(value)
    return rows


def _index(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("adc_id", "")).strip(), str(row.get("field", "")).strip())
        if not all(key) or key in indexed:
            raise ValueError(f"{label}: duplicate or incomplete review key {key!r}")
        indexed[key] = row
    return indexed


def _require_slot(
    rows: list[dict[str, Any]],
    *,
    slot: str,
    origin: str,
    label: str,
) -> None:
    for row in rows:
        verification = row.get("verification")
        if not isinstance(verification, dict):
            raise ValueError(f"{label}: verification must be an object")
        if verification.get("reviewer_slot") != slot or verification.get("review_origin") != origin:
            raise ValueError(
                f"{label}: every completed item must use "
                f"reviewer_slot={slot} and review_origin={origin}"
            )


def _signature(row: dict[str, Any]) -> tuple[Any, ...]:
    verification = row["verification"]
    assert isinstance(verification, dict)
    return (
        verification.get("status"),
        verification.get("verdict"),
        verification.get("confirmed_value"),
    )


def merge_catalog_field_reviews(
    primary_packet: Path,
    secondary_packet: Path,
    manifest: Path,
    catalog: Path,
    *,
    adjudicator_packet: Path | None = None,
) -> dict[str, Any]:
    """Validate and pair independent packets, optionally applying adjudication metadata."""
    primary_rows = _read_jsonl(primary_packet)
    secondary_rows = _read_jsonl(secondary_packet)
    validate_review_packet(primary_packet, manifest, catalog_path=catalog, require_complete=True)
    validate_review_packet(secondary_packet, manifest, catalog_path=catalog, require_complete=True)
    _require_slot(primary_rows, slot="primary", origin="human_independent", label="primary packet")
    _require_slot(secondary_rows, slot="secondary", origin="human_independent", label="secondary packet")

    primary = _index(primary_rows, "primary packet")
    secondary = _index(secondary_rows, "secondary packet")
    if set(primary) != set(secondary):
        raise ValueError("primary and secondary packets contain different review keys")

    disagreements: list[dict[str, Any]] = []
    paired: list[dict[str, Any]] = []
    for key in sorted(primary):
        left, right = primary[key], secondary[key]
        left_signature = _signature(left)
        right_signature = _signature(right)
        item = {
            "review_item_id": left.get("review_item_id"),
            "adc_id": key[0],
            "field": key[1],
            "primary": {
                "status": left_signature[0],
                "verdict": left_signature[1],
                "confirmed_value": left_signature[2],
                "source_locator": left["verification"].get("source_locator"),
            },
            "secondary": {
                "status": right_signature[0],
                "verdict": right_signature[1],
                "confirmed_value": right_signature[2],
                "source_locator": right["verification"].get("source_locator"),
            },
            "agreement": left_signature == right_signature,
        }
        if not item["agreement"]:
            disagreements.append({"review_item_id": item["review_item_id"], "adc_id": key[0], "field": key[1]})
        paired.append(item)

    adjudicated_count = 0
    adjudication: dict[tuple[str, str], dict[str, Any]] = {}
    if adjudicator_packet is not None:
        adjudicator_rows = _read_jsonl(adjudicator_packet)
        validate_review_packet(adjudicator_packet, manifest, catalog_path=catalog, require_complete=True)
        _require_slot(
            adjudicator_rows,
            slot="adjudicator",
            origin="human_adjudicated",
            label="adjudicator packet",
        )
        adjudication = _index(adjudicator_rows, "adjudicator packet")
        if set(adjudication) != set(primary):
            raise ValueError("adjudicator packet contains different review keys")
        for item in disagreements:
            row = adjudication[(item["adc_id"], item["field"])]
            verification = row["verification"]
            assert isinstance(verification, dict)
            if verification.get("status") != "adjudicated":
                raise ValueError(
                    f"adjudicator packet must mark disagreement as adjudicated: {item['review_item_id']}"
                )
            item["adjudicated"] = True
            adjudicated_count += 1

    disagreement_count = len(disagreements)
    return {
        "schema_version": "public-adc-catalog-field-review-pair-v1",
        "catalog_sha256": validate_review_packet(
            primary_packet, manifest, catalog_path=catalog, require_complete=True
        )["catalog_sha256"],
        "item_count": len(paired),
        "agreement_count": len(paired) - disagreement_count,
        "disagreement_count": disagreement_count,
        "adjudicated_disagreement_count": adjudicated_count,
        "independent_review_complete": True,
        "review_ready": disagreement_count == 0 or adjudicated_count == disagreement_count,
        "status": (
            "ready_for_catalog_update"
            if disagreement_count == 0 or adjudicated_count == disagreement_count
            else "needs_adjudication"
        ),
        "disagreements": disagreements,
        "paired_items": paired,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--secondary", type=Path, required=True)
    parser.add_argument("--adjudicator", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = merge_catalog_field_reviews(
        args.primary,
        args.secondary,
        args.manifest,
        args.catalog,
        adjudicator_packet=args.adjudicator,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "item_count", "agreement_count", "disagreement_count",
        "adjudicated_disagreement_count", "review_ready", "status",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
