"""Validate the public ADC catalog's field-level source review packet.

The packet is intentionally separate from the catalog.  This validator checks
that every catalog row and review field has exactly one item, that pending
items remain visibly pending, and that a completed item has a locator and a
verdict.  It never infers a verdict from the candidate URL or from an
automatic content scan.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

try:  # Works both as ``python -m scripts...`` and as a direct script path.
    from scripts.build_catalog_field_review_packet import KEY_FIELDS
except ModuleNotFoundError:  # pragma: no cover - exercised by the CLI smoke test
    from build_catalog_field_review_packet import KEY_FIELDS


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"

_PENDING = {"pending_primary_check"}
_COMPLETED = {"reviewed_primary_source", "adjudicated", "rejected", "unclear"}
_VERDICTS = {"supported", "contradicted", "not_found", "unclear"}
_INDEPENDENT_SLOTS = {"primary", "secondary"}


def _canonical_hash(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number}: invalid JSON") from exc
            if not isinstance(value, dict):
                raise ValueError(f"line {line_number}: item must be an object")
            items.append(value)
    return items


def validate_review_packet(
    packet_path: Path,
    manifest_path: Path,
    *,
    catalog_path: Path | None = None,
    require_complete: bool = False,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "public-adc-catalog-field-review-v1":
        raise ValueError("unsupported review manifest schema")
    items = _read_jsonl(packet_path)
    expected_ids: list[str]
    expected_catalog_sha = None
    if catalog_path is not None:
        with catalog_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        expected_ids = [str(row.get("adc_id", "")).strip() for row in rows]
        expected_catalog_sha = _canonical_hash(catalog_path)
        if manifest.get("catalog_sha256") != expected_catalog_sha:
            raise ValueError("review manifest catalog_sha256 does not match catalog")
        if manifest.get("catalog_row_count") != len(rows):
            raise ValueError("review manifest catalog_row_count does not match catalog")
    else:
        expected_ids = sorted({str(item.get("adc_id", "")).strip() for item in items})

    expected_keys = {(adc_id, field) for adc_id in expected_ids for field in KEY_FIELDS}
    seen: set[tuple[str, str]] = set()
    status_counts: dict[str, int] = {}
    pending_count = 0
    completed_count = 0
    for position, item in enumerate(items, 1):
        adc_id = str(item.get("adc_id", "")).strip()
        field = str(item.get("field", "")).strip()
        key = (adc_id, field)
        if key not in expected_keys:
            raise ValueError(f"item {position}: unexpected adc_id/field pair {key!r}")
        if key in seen:
            raise ValueError(f"item {position}: duplicate adc_id/field pair {key!r}")
        seen.add(key)
        expected_id = f"{adc_id}:{field}"
        if item.get("review_item_id") != expected_id:
            raise ValueError(f"item {position}: review_item_id must be {expected_id!r}")
        verification = item.get("verification")
        if not isinstance(verification, dict):
            raise ValueError(f"item {position}: verification must be an object")
        candidate_source = item.get("candidate_source")
        if not isinstance(candidate_source, dict):
            raise ValueError(f"item {position}: candidate_source must be an object")
        locators = candidate_source.get("field_locator_candidates", [])
        if not isinstance(locators, list):
            raise ValueError(f"item {position}: field_locator_candidates must be a list")
        for locator in locators:
            if not isinstance(locator, dict) or not str(locator.get("source_url", "")).startswith("https://"):
                raise ValueError(f"item {position}: candidate locator needs an HTTPS source_url")
        status = str(verification.get("status", "")).strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        if status not in _PENDING | _COMPLETED:
            raise ValueError(f"item {position}: unsupported verification status {status!r}")
        verdict = verification.get("verdict")
        locator = verification.get("source_locator")
        if status in _PENDING:
            pending_count += 1
            if verdict is not None or locator is not None:
                raise ValueError(f"item {position}: pending item must have blank verdict and locator")
            if verification.get("reviewer_slot") is not None or verification.get("review_origin") is not None:
                raise ValueError(f"item {position}: pending item must have blank reviewer metadata")
        else:
            completed_count += 1
            if verdict not in _VERDICTS:
                raise ValueError(f"item {position}: completed item needs a controlled verdict")
            if not isinstance(locator, str) or not locator.strip():
                raise ValueError(f"item {position}: completed item needs a source locator")
            reviewer_slot = str(verification.get("reviewer_slot", "")).strip()
            review_origin = str(verification.get("review_origin", "")).strip()
            if status == "adjudicated":
                if reviewer_slot != "adjudicator" or review_origin != "human_adjudicated":
                    raise ValueError(
                        f"item {position}: adjudicated item needs reviewer_slot=adjudicator "
                        "and review_origin=human_adjudicated"
                    )
            elif reviewer_slot not in _INDEPENDENT_SLOTS or review_origin != "human_independent":
                raise ValueError(
                    f"item {position}: completed item needs an independent human reviewer "
                    "(primary/secondary with review_origin=human_independent)"
                )
    missing = sorted(expected_keys - seen)
    if missing:
        raise ValueError(f"review packet is missing {len(missing)} expected items")
    if require_complete and pending_count:
        raise ValueError(f"review packet still has {pending_count} pending items")
    return {
        "schema_version": "public-adc-catalog-field-review-validation-v1",
        "packet_path": packet_path.name,
        "manifest_path": manifest_path.name,
        "catalog_sha256": expected_catalog_sha or manifest.get("catalog_sha256"),
        "catalog_row_count": len(expected_ids),
        "expected_item_count": len(expected_keys),
        "item_count": len(items),
        "pending_count": pending_count,
        "completed_count": completed_count,
        "status_counts": dict(sorted(status_counts.items())),
        "review_ready": pending_count == 0,
        "validation_status": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    report = validate_review_packet(
        args.packet,
        args.manifest,
        catalog_path=args.catalog,
        require_complete=args.require_complete,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
