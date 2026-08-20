from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlencode

from adc_evidence.ingestion.http import fetch_bytes, sha256_bytes, utc_now, write_snapshot
from adc_evidence.records import DocumentRecord, SourceRecord


API_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def build_pubmed_query(adc_names: list[str]) -> str:
    adc_terms = " OR ".join(f'"{name}"[Title/Abstract]' for name in adc_names)
    target_terms = " OR ".join(
        f'"{term}"[Title/Abstract]'
        for term in ("HER2", "ERBB2", "TROP2", "TROP-2", "TACSTD2")
    )
    adc_concept = (
        '"antibody-drug conjugate"[Title/Abstract] OR '
        '"antibody drug conjugate"[Title/Abstract] OR ADC[Title/Abstract]'
    )
    return f"({adc_concept}) AND (({target_terms}) OR ({adc_terms}))"


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = "".join(element.itertext()).strip()
    return value or None


def _publication_date(article: ET.Element) -> str | None:
    pub_date = article.find("./MedlineCitation/Article/Journal/JournalIssue/PubDate")
    if pub_date is None:
        return None
    year = _text(pub_date.find("Year"))
    month = _text(pub_date.find("Month"))
    day = _text(pub_date.find("Day"))
    if year:
        return "-".join(item for item in (year, month, day) if item)
    return _text(pub_date.find("MedlineDate"))


def parse_pubmed_xml(
    content: bytes,
    *,
    raw_path: str,
    checksum: str,
) -> list[DocumentRecord]:
    root = ET.fromstring(content)
    documents: list[DocumentRecord] = []
    for article in root.findall("PubmedArticle"):
        citation = article.find("MedlineCitation")
        article_node = citation.find("Article") if citation is not None else None
        if citation is None or article_node is None:
            continue
        pmid = _text(citation.find("PMID"))
        title = _text(article_node.find("ArticleTitle"))
        if not pmid or not title:
            continue

        abstract_parts: list[str] = []
        for abstract_node in article_node.findall("./Abstract/AbstractText"):
            value = _text(abstract_node)
            if not value:
                continue
            label = abstract_node.attrib.get("Label")
            abstract_parts.append(f"{label}: {value}" if label else value)

        authors: list[str] = []
        for author in article_node.findall("./AuthorList/Author"):
            collective = _text(author.find("CollectiveName"))
            if collective:
                authors.append(collective)
                continue
            last_name = _text(author.find("LastName"))
            initials = _text(author.find("Initials"))
            name = " ".join(item for item in (last_name, initials) if item)
            if name:
                authors.append(name)

        doi: str | None = None
        for article_id in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            if article_id.attrib.get("IdType") == "doi":
                doi = _text(article_id)
                break

        documents.append(
            DocumentRecord(
                document_id=f"pubmed:{pmid}",
                source="pubmed",
                source_record_id=pmid,
                title=title,
                abstract="\n".join(abstract_parts) or None,
                authors=authors,
                journal=_text(article_node.find("./Journal/Title")),
                publication_date=_publication_date(article),
                doi=doi,
                source_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                raw_path=raw_path,
                checksum=checksum,
            )
        )
    return documents


def collect_pubmed(
    adc_names: list[str],
    raw_directory: Path,
    *,
    max_records: int = 200,
    batch_size: int = 100,
) -> tuple[list[DocumentRecord], list[SourceRecord], str, int]:
    query = build_pubmed_query(adc_names)
    common = {
        "db": "pubmed",
        "tool": "adc_evidence_mvp",
        "email": os.getenv("NCBI_EMAIL", ""),
    }
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        common["api_key"] = api_key

    search_parameters = {
        **common,
        "term": query,
        "retmode": "json",
        "retmax": str(max_records),
        "sort": "relevance",
    }
    search_url = f"{API_BASE}/esearch.fcgi?{urlencode(search_parameters)}"
    search_content = fetch_bytes(search_url, timeout=45)
    search_path, search_checksum = write_snapshot(
        raw_directory / "esearch.json", search_content
    )
    search_payload = json.loads(search_content)
    search_result = search_payload.get("esearchresult", {})
    pmids = search_result.get("idlist", [])
    total_count = int(search_result.get("count", 0))
    retrieved_at = utc_now()
    source_records = [
        SourceRecord(
            source="pubmed",
            source_record_id="esearch",
            retrieved_at=retrieved_at,
            source_url=search_url,
            raw_path=search_path,
            sha256=search_checksum,
            dataset_version=retrieved_at,
        )
    ]

    documents: list[DocumentRecord] = []
    for batch_number, start in enumerate(range(0, len(pmids), batch_size), start=1):
        batch = pmids[start : start + batch_size]
        fetch_parameters = {
            **common,
            "id": ",".join(batch),
            "retmode": "xml",
        }
        fetch_url = f"{API_BASE}/efetch.fcgi?{urlencode(fetch_parameters)}"
        content = fetch_bytes(fetch_url, timeout=60)
        checksum = sha256_bytes(content)
        path, _ = write_snapshot(
            raw_directory / f"efetch_{batch_number:03d}.xml", content
        )
        batch_documents = parse_pubmed_xml(content, raw_path=path, checksum=checksum)
        documents.extend(batch_documents)
        for document in batch_documents:
            source_records.append(
                SourceRecord(
                    source="pubmed",
                    source_record_id=document.source_record_id,
                    retrieved_at=retrieved_at,
                    source_url=document.source_url,
                    raw_path=path,
                    sha256=checksum,
                    dataset_version=retrieved_at,
                )
            )

    unique_documents = {document.document_id: document for document in documents}
    return list(unique_documents.values()), source_records, query, total_count
