"""Audit completeness and source specificity of the public ADC catalog."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT_ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "public" / "marketed_adc_catalog.audit.json"
REQUIRED_FIELDS = (
    "adc_name", "aliases", "target", "antibody", "linker_name", "linker_type",
    "payload_name", "payload_class", "indication", "company", "source_url",
    "brand_name", "approval_date", "approval_jurisdictions", "catalog_status",
    "as_of_date", "verification_status",
)
GENERIC_SOURCE_URLS = {
    "https://www.nmpa.gov.cn/",
    "https://www.fda.gov/drugs/resources-information-approved-drugs",
    "https://www.fda.gov/drugs/resources-information-approved-drugs/",
}


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _is_generic_source(url: str) -> bool:
    normalized = url.strip().rstrip("/") + "/"
    if normalized in GENERIC_SOURCE_URLS:
        return True
    parsed = urlparse(url)
    return parsed.path in {"", "/"} and bool(parsed.netloc)


def _parse_iso(value: str, field: str, adc_id: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{adc_id}: invalid {field}={value!r}") from exc


def audit_catalog(catalog: Path, *, requested_as_of: str) -> dict[str, object]:
    """Return a deterministic audit report for a catalog CSV."""
    catalog = catalog.resolve()
    if not catalog.is_file():
        raise FileNotFoundError(catalog)
    _parse_iso(requested_as_of, "requested_as_of", "catalog")
    with catalog.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("Public ADC catalog must not be empty")
    ids = [str(row.get("adc_id", "")).strip() for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Catalog must contain unique nonempty adc_id values")

    status_counts: dict[str, int] = {}
    queue: list[dict[str, object]] = []
    generic_source_count = 0
    missing_field_count = 0
    future_approval_count = 0
    for row in rows:
        adc_id = str(row["adc_id"]).strip()
        reasons: list[str] = []
        status = str(row.get("catalog_status", "")).strip()
        status_counts[status] = status_counts.get(status, 0) + 1
        missing = [field for field in REQUIRED_FIELDS if not str(row.get(field, "")).strip()]
        if missing:
            missing_field_count += 1
            reasons.append("missing_fields:" + ",".join(missing))
        if _is_generic_source(str(row.get("source_url", ""))):
            generic_source_count += 1
            reasons.append("generic_source_url")
        verification = str(row.get("verification_status", "")).strip()
        if verification != "reviewed_primary_source":
            reasons.append("verification_status:" + (verification or "missing"))
        approval = str(row.get("approval_date", "")).strip()
        if approval:
            approval_date = _parse_iso(approval, "approval_date", adc_id)
            if approval_date > _parse_iso(requested_as_of, "requested_as_of", adc_id):
                future_approval_count += 1
                reasons.append("approval_after_requested_as_of")
        if reasons:
            queue.append({"adc_id": adc_id, "adc_name": str(row.get("adc_name", "")), "reasons": reasons})

    return {
        "schema_version": "public-adc-catalog-audit-v1",
        "catalog_sha256": _sha256(catalog),
        "requested_as_of": requested_as_of,
        "row_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "required_field_count": len(REQUIRED_FIELDS),
        "rows_with_missing_required_fields": missing_field_count,
        "generic_source_url_count": generic_source_count,
        "approval_after_requested_as_of_count": future_approval_count,
        "verification_status_counts": {
            value: sum(str(row.get("verification_status", "")).strip() == value for row in rows)
            for value in sorted({str(row.get("verification_status", "")).strip() for row in rows})
        },
        "review_status": "needs_primary_source_review" if queue else "ready_for_catalog_review",
        "manual_review_queue": queue,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--requested-as-of", default="2026-09-30")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = audit_catalog(args.catalog, requested_as_of=args.requested_as_of)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("review_status", "row_count", "generic_source_url_count", "rows_with_missing_required_fields")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
