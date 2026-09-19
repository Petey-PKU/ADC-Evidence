"""Build a field-level primary-source review packet from the public catalog."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_CANDIDATE_LOCATORS = ROOT / "data" / "public" / "catalog_source_locator_candidates.jsonl"

KEY_FIELDS = (
    "target", "antibody", "linker_name", "linker_type", "payload_name",
    "payload_class", "dar", "indication", "development_status", "company",
    "approval_date", "approval_jurisdictions", "catalog_status",
)


def _canonical_hash(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _load_candidate_locators(path: Path | None) -> dict[tuple[str, str], list[dict[str, object]]]:
    """Load field-level source hints without treating them as review verdicts."""
    if path is None or not path.exists():
        return {}
    grouped: dict[tuple[str, str], list[dict[str, object]]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"candidate locator line {line_number}: invalid JSON") from exc
        if not isinstance(row, dict):
            raise ValueError(f"candidate locator line {line_number}: item must be an object")
        adc_id = str(row.get("adc_id", "")).strip()
        field = str(row.get("field", "")).strip()
        source_url = str(row.get("source_url", "")).strip()
        if not adc_id or not field or not source_url.startswith("https://"):
            raise ValueError(f"candidate locator line {line_number}: needs adc_id, field and HTTPS source_url")
        grouped.setdefault((adc_id, field), []).append({
            key: row[key]
            for key in (
                "candidate_value", "source_url", "source_locator", "source_tier",
                "support_status", "note", "review_status",
            )
            if key in row
        })
    return grouped


def build_packet(
    catalog_path: Path,
    candidate_locator_path: Path | None = DEFAULT_CANDIDATE_LOCATORS,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Return one blank-review item for every ADC/key-field pair."""
    with catalog_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Catalog must not be empty")
    ids = [str(row.get("adc_id", "")).strip() for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Catalog must contain unique nonempty adc_id values")
    candidate_locators = _load_candidate_locators(candidate_locator_path)

    packet: list[dict[str, object]] = []
    for row in rows:
        adc_id = str(row["adc_id"]).strip()
        for field in KEY_FIELDS:
            value = str(row.get(field, "") or "").strip()
            packet.append({
                "review_item_id": f"{adc_id}:{field}",
                "adc_id": adc_id,
                "adc_name": str(row.get("adc_name", "")).strip(),
                "field": field,
                "candidate_value": value,
                "value_status": "missing" if not value else "present",
                "candidate_source": {
                    "source_type": "curated_seed",
                    "source_url": str(row.get("source_url", "")).strip(),
                    "source_role": "candidate_primary_source",
                    "field_locator_candidates": candidate_locators.get((adc_id, field), []),
                },
                "verification": {
                    "status": "pending_primary_check",
                    "reviewer_slot": None,
                    "review_origin": None,
                    "verdict": None,
                    "confirmed_value": None,
                    "source_locator": None,
                    "notes": None,
                },
            })
    manifest = {
        "schema_version": "public-adc-catalog-field-review-v1",
        "catalog_sha256": _canonical_hash(catalog_path),
        "catalog_row_count": len(rows),
        "review_item_count": len(packet),
        "candidate_locator_file": candidate_locator_path.name if candidate_locator_path else None,
        "candidate_locator_sha256": _canonical_hash(candidate_locator_path) if candidate_locator_path and candidate_locator_path.exists() else None,
        "candidate_locator_count": sum(len(values) for values in candidate_locators.values()),
        "key_fields": list(KEY_FIELDS),
        "status": "awaiting_independent_primary_source_review",
        "review_instructions": (
            "Review each field against the linked regulator or first-party source. "
            "Record a verdict and confirmed value only after checking the source; "
            "use two independent reviewer slots and keep disagreements for adjudication."
        ),
        "ai_assisted_labels_accepted": False,
    }
    return packet, manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--candidate-locators", type=Path, default=DEFAULT_CANDIDATE_LOCATORS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    packet, manifest = build_packet(args.catalog, args.candidate_locators)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in packet),
        encoding="utf-8",
    )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
