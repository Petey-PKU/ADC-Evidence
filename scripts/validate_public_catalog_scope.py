"""Validate the explicit modality boundary for the public ADC catalog."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_POLICY = ROOT / "data" / "public" / "catalog_scope_policy.json"
ALLOWED_CATALOG_STATUSES = {"marketed", "withdrawn", "approved_not_marketed"}


def validate_catalog_scope(catalog: Path, policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    if policy.get("schema_version") != "public-adc-catalog-scope-v1":
        raise ValueError("unsupported catalog scope policy schema")
    classes = policy.get("classes")
    records = policy.get("records")
    if not isinstance(classes, dict) or not isinstance(records, dict) or not records:
        raise ValueError("scope policy needs nonempty classes and records objects")
    for modality, definition in classes.items():
        if not isinstance(definition, dict) or not isinstance(definition.get("definition"), str):
            raise ValueError(f"scope class {modality!r} needs a definition")
        if not isinstance(definition.get("included_in_core"), bool):
            raise ValueError(f"scope class {modality!r} needs included_in_core")
    unknown_classes = sorted(set(records.values()) - set(classes))
    if unknown_classes:
        raise ValueError(f"scope policy references unknown classes: {unknown_classes}")
    with catalog.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    catalog_ids = [str(row.get("adc_id", "")).strip() for row in rows]
    if not catalog_ids or any(not value for value in catalog_ids) or len(catalog_ids) != len(set(catalog_ids)):
        raise ValueError("catalog needs unique nonempty adc_id values")
    policy_ids = set(records)
    catalog_id_set = set(catalog_ids)
    missing_policy = sorted(catalog_id_set - policy_ids)
    extra_policy = sorted(policy_ids - catalog_id_set)
    if missing_policy or extra_policy:
        raise ValueError(f"scope policy/catalog IDs differ; missing={missing_policy}, extra={extra_policy}")
    invalid_statuses = sorted({str(row.get("catalog_status", "")).strip() for row in rows} - ALLOWED_CATALOG_STATUSES)
    if invalid_statuses:
        raise ValueError(f"unsupported catalog_status values: {invalid_statuses}")
    class_counts = Counter(records[adc_id] for adc_id in catalog_ids)
    core_ids = [adc_id for adc_id in catalog_ids if classes[records[adc_id]]["included_in_core"]]
    extended_ids = [adc_id for adc_id in catalog_ids if not classes[records[adc_id]]["included_in_core"]]
    return {
        "schema_version": "public-adc-catalog-scope-validation-v1",
        "catalog_path": catalog.name,
        "policy_path": policy_path.name,
        "policy_status": policy.get("policy_status"),
        "target_window": policy.get("target_window"),
        "catalog_row_count": len(catalog_ids),
        "core_row_count": len(core_ids),
        "extended_row_count": len(extended_ids),
        "class_counts": dict(sorted(class_counts.items())),
        "core_adc_ids": core_ids,
        "extended_adc_ids": extended_ids,
        "validation_status": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args()
    print(json.dumps(validate_catalog_scope(args.catalog, args.policy), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
