"""Audit candidate catalog URLs without turning matches into gold labels.

The catalog stores one candidate URL per ADC. This report deliberately marks
structural fields as lacking a field-level source unless a future reviewer
supplies a locator. HTTP reachability and name matching are triage signals only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "public" / "marketed_adc_catalog.csv"
DEFAULT_CANDIDATE_LOCATORS = ROOT / "data" / "public" / "catalog_source_locator_candidates.jsonl"
KEY_FIELDS = (
    "target", "antibody", "linker_name", "linker_type", "payload_name",
    "payload_class", "dar", "indication", "development_status", "company",
    "approval_date", "approval_jurisdictions", "catalog_status",
)
STRUCTURAL_FIELDS = {
    "target", "antibody", "linker_name", "linker_type", "payload_name",
    "payload_class", "dar",
}


def source_class(url: str) -> str:
    host = urlparse(url).netloc.casefold()
    if host.endswith("fda.gov"):
        return "regulator_fda"
    if host.endswith("pmda.go.jp"):
        return "regulator_pmda"
    if host.endswith("nmpa.gov.cn"):
        return "regulator_nmpa"
    if host.endswith("ema.europa.eu"):
        return "regulator_ema"
    if host.endswith("hkexnews.hk") or host.endswith("cninfo.com.cn"):
        return "issuer_filing"
    return "first_party_or_other"


def _fetch(url: str, timeout: int) -> tuple[int, str, str]:
    request = Request(url, headers={"User-Agent": "ADC-Evidence-source-audit/0.6", "Accept-Encoding": "identity"})
    with urlopen(request, timeout=timeout) as response:
        content = response.read()
        return int(response.status), response.headers.get_content_type(), content.decode("utf-8", errors="ignore")


def _candidate_pairs(path: Path | None) -> set[tuple[str, str]]:
    if path is None:
        return set()
    pairs: set[tuple[str, str]] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"candidate locator line {line_number} must be an object")
        adc_id = str(row.get("adc_id", "")).strip()
        field = str(row.get("field", "")).strip()
        if not adc_id or not field or not str(row.get("source_url", "")).startswith("https://"):
            raise ValueError(f"candidate locator line {line_number} needs adc_id, field and HTTPS source_url")
        pairs.add((adc_id, field))
    return pairs


def audit_catalog_sources(
    catalog: Path,
    *,
    timeout: int = 12,
    candidate_locators: Path | None = None,
) -> dict[str, object]:
    with catalog.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("catalog must not be empty")
    candidate_pairs = _candidate_pairs(candidate_locators)
    structural_pairs = {
        (str(row.get("adc_id", "")).strip(), field)
        for row in rows
        for field in STRUCTURAL_FIELDS
    }
    results: list[dict[str, object]] = []
    for row in rows:
        adc_id = str(row.get("adc_id", "")).strip()
        name = str(row.get("adc_name", "")).strip()
        aliases = [item.strip() for item in str(row.get("aliases", "")).split("|") if item.strip()]
        url = str(row.get("source_url", "")).strip()
        item: dict[str, object] = {
            "adc_id": adc_id, "adc_name": name, "source_url": url,
            "source_class": source_class(url), "http_status": None,
            "content_type": None, "name_or_alias_match": False,
            "inspection_status": "pending", "fetch_status": "pending", "field_assessment": {},
            "review_required": True,
        }
        match = False
        try:
            status, content_type, content = _fetch(url, timeout)
            if content_type == "application/pdf":
                item["inspection_status"] = "pdf_text_not_extracted"
            else:
                haystack = re.sub(r"\s+", " ", content).casefold()
                match = any(term.casefold() in haystack for term in (name, *aliases) if len(term) >= 4)
                item["inspection_status"] = "text_scanned"
            item.update(http_status=status, content_type=content_type,
                        name_or_alias_match=match,
                        fetch_status="reachable" if status < 400 else "http_error")
        except HTTPError as error:
            item.update(fetch_status="http_error", http_status=int(error.code),
                        content_type=error.headers.get_content_type() if error.headers else None,
                        error_type=type(error).__name__)
        except (URLError, TimeoutError, OSError, ValueError) as error:
            item.update(fetch_status="fetch_error", error_type=type(error).__name__)
        field_assessment = item["field_assessment"]
        assert isinstance(field_assessment, dict)
        for field in KEY_FIELDS:
            if field in STRUCTURAL_FIELDS:
                assessment = (
                    "candidate_locator_pending_human_review"
                    if (adc_id, field) in candidate_pairs
                    else "field_level_source_missing"
                )
            elif match and field in {"catalog_status", "approval_date", "approval_jurisdictions", "development_status", "indication"}:
                assessment = "candidate_support_only"
            else:
                assessment = "source_content_not_confirmed"
            field_assessment[field] = assessment
        results.append(item)
    match_count = sum(bool(item["name_or_alias_match"]) for item in results)
    return {
        "schema_version": "public-adc-source-content-audit-v1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "catalog_path": catalog.name, "catalog_row_count": len(results),
        "reachable_or_http_error_count": sum(item["fetch_status"] in {"reachable", "http_error"} for item in results),
        "name_or_alias_match_count": match_count,
        "candidate_locator_file": candidate_locators.name if candidate_locators else None,
        "candidate_locator_pair_count": len(candidate_pairs),
        "structural_field_pair_count": len(structural_pairs),
        "structural_field_candidate_locator_count": len(structural_pairs & candidate_pairs),
        "structural_field_candidate_locator_missing_count": len(structural_pairs - candidate_pairs),
        "structural_field_candidate_locator_coverage_ratio": (
            round(len(structural_pairs & candidate_pairs) / len(structural_pairs), 4)
            if structural_pairs else None
        ),
        "field_level_source_missing_count": len(structural_pairs - candidate_pairs),
        "review_status": "triage_only_pending_human_source_locator_review",
        "ai_or_automatic_labels_are_gold": False, "records": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--candidate-locators", type=Path, default=DEFAULT_CANDIDATE_LOCATORS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()
    report = audit_catalog_sources(args.catalog, timeout=args.timeout, candidate_locators=args.candidate_locators)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "schema_version", "catalog_row_count", "reachable_or_http_error_count",
        "name_or_alias_match_count", "structural_field_candidate_locator_count",
        "structural_field_candidate_locator_missing_count", "review_status",
    )}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
