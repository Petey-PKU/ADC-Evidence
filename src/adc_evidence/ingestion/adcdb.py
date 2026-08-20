from __future__ import annotations

import html
import re
import time
from pathlib import Path
from urllib.parse import quote

from adc_evidence.ingestion.http import fetch_bytes, sha256_bytes, utc_now, write_snapshot
from adc_evidence.records import ADCdbRecord, SourceRecord


BASE_URL = "https://adcdb.idrblab.net"


def _clean_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "; ", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def _extract_table_fields(content: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    pattern = re.compile(
        r"<th[^>]*>\s*(?P<label>[^<]+?)\s*</th>\s*"
        r"<td[^>]*>\s*(?:<div[^>]*>)?(?P<value>.*?)(?:</div>)?\s*</td>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(content):
        label = _clean_html(match.group("label"))
        value = _clean_html(match.group("value"))
        if label and value and label not in fields:
            fields[label] = value
    return fields


def _parse_float(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def _normalize_name(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.casefold()).split())


def parse_adcdb_search_results(content: bytes) -> list[tuple[str, str, str]]:
    decoded = content.decode("utf-8", errors="replace")
    pattern = re.compile(
        r"ADC ID:\s*(?P<id>[A-Z0-9]+).*?"
        r"<b>ADC Name:\s*</b>(?P<name>.*?)</span>.*?"
        r'href=["\'](?P<path>/data/adc/details/[A-Z0-9]+)["\']',
        flags=re.IGNORECASE | re.DOTALL,
    )
    return [
        (
            match.group("id"),
            _clean_html(match.group("name")),
            match.group("path"),
        )
        for match in pattern.finditer(decoded)
    ]


def parse_adcdb_detail(
    content: bytes,
    *,
    detail_url: str,
    raw_path: str,
    checksum: str,
) -> ADCdbRecord:
    decoded = content.decode("utf-8", errors="replace")
    fields = _extract_table_fields(decoded)
    adcdb_id = fields.get("ADC ID")
    adc_name = fields.get("ADC Name")
    if not adcdb_id or not adc_name:
        raise ValueError(f"ADCdb detail page did not contain ADC ID/name: {detail_url}")
    synonyms = [
        item.strip()
        for item in (fields.get("Synonyms") or "").split(";")
        if item.strip()
    ]
    return ADCdbRecord(
        adcdb_id=adcdb_id,
        adc_name=adc_name,
        brand_name=fields.get("Brand Name"),
        synonyms=synonyms,
        organization=fields.get("Organization"),
        drug_status=fields.get("Drug Status"),
        dar=_parse_float(fields.get("Drug-to-Antibody Ratio")),
        antibody_name=fields.get("Antibody Name"),
        antigen_name=fields.get("Antigen Name"),
        payload_name=fields.get("Payload Name"),
        linker_name=fields.get("Linker Name"),
        representative_indication=fields.get("Representative Indication"),
        detail_url=detail_url,
        raw_path=raw_path,
        checksum=checksum,
        raw_fields=fields,
    )


def collect_adcdb(
    adc_names: list[str],
    raw_directory: Path,
    *,
    delay_seconds: float = 0.4,
) -> tuple[list[ADCdbRecord], list[SourceRecord], list[str]]:
    records: list[ADCdbRecord] = []
    source_records: list[SourceRecord] = []
    errors: list[str] = []
    retrieved_at = utc_now()

    for index, adc_name in enumerate(adc_names, start=1):
        try:
            search_url = (
                f"{BASE_URL}/search/result/adc?search_api_fulltext="
                f"{quote(chr(34) + adc_name + chr(34))}"
            )
            search_content = fetch_bytes(search_url, timeout=45)
            search_path, _ = write_snapshot(
                raw_directory / f"search_{index:03d}.html", search_content
            )
            search_results = parse_adcdb_search_results(search_content)
            selected = next(
                (
                    result
                    for result in search_results
                    if _normalize_name(result[1]) == _normalize_name(adc_name)
                ),
                None,
            )
            if selected is None:
                returned_names = ", ".join(result[1] for result in search_results)
                raise ValueError(
                    f"No exact ADCdb result; returned: {returned_names or 'none'}"
                )
            adcdb_id, _, detail_path_fragment = selected
            detail_url = f"{BASE_URL}{detail_path_fragment}"
            detail_content = fetch_bytes(detail_url, timeout=60)
            checksum = sha256_bytes(detail_content)
            detail_path, _ = write_snapshot(
                raw_directory / f"{adcdb_id}.html", detail_content
            )
            record = parse_adcdb_detail(
                detail_content,
                detail_url=detail_url,
                raw_path=detail_path,
                checksum=checksum,
            )
            records.append(record)
            source_records.append(
                SourceRecord(
                    source="adcdb",
                    source_record_id=record.adcdb_id,
                    retrieved_at=retrieved_at,
                    source_url=detail_url,
                    raw_path=detail_path,
                    sha256=checksum,
                    dataset_version=retrieved_at,
                )
            )
            time.sleep(delay_seconds)
        except Exception as error:  # continue so one website record cannot abort the run
            errors.append(f"{adc_name}: {error}")

    return records, source_records, errors
