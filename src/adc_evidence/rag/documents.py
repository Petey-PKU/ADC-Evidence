from __future__ import annotations

import hashlib
import json
import re
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from adc_evidence.config import DEFAULT_DATABASE_PATH
from adc_evidence.database import connect, create_database


@dataclass(frozen=True)
class RetrievalDocument:
    retrieval_document_id: str
    source_type: str
    source_record_id: str
    title: str
    content: str
    source_url: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    retrieval_document_id: str
    chunk_index: int
    title: str
    content: str
    metadata: dict[str, Any]


def _json_list(value: str | None) -> list[str]:
    if not value:
        return []
    parsed = json.loads(value)
    return [str(item) for item in parsed]


def _clean(value: object | None) -> str:
    return " ".join(str(value or "").split())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _linked_entities(connection, record_type: str, record_id: str) -> dict[str, list[str]]:
    rows = connection.execute(
        """
        SELECT entity_type, entity_id
        FROM entity_links
        WHERE source_record_type = ? AND source_record_id = ?
        GROUP BY entity_type, entity_id
        ORDER BY entity_type, entity_id
        """,
        (record_type, record_id),
    ).fetchall()
    entities: dict[str, list[str]] = {}
    for row in rows:
        entities.setdefault(str(row["entity_type"]), []).append(str(row["entity_id"]))

    adc_ids = entities.get("adc", [])
    if adc_ids:
        placeholders = ",".join("?" for _ in adc_ids)
        names = connection.execute(
            f"SELECT adc_id, adc_name FROM adcs WHERE adc_id IN ({placeholders})",
            adc_ids,
        ).fetchall()
        entities["adc_names"] = [str(row["adc_name"]) for row in names]
    return entities


def _adc_documents(connection) -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for row in connection.execute("SELECT * FROM adcs ORDER BY adc_id"):
        aliases = [
            str(item[0])
            for item in connection.execute(
                "SELECT alias FROM adc_aliases WHERE adc_id = ? ORDER BY alias",
                (row["adc_id"],),
            ).fetchall()
        ]
        lines = [
            f"ADC 名称 / ADC name: {_clean(row['adc_name'])}",
            f"别名 / aliases: {', '.join(aliases) or 'not recorded'}",
            f"靶点 / target: {_clean(row['target'])}",
            f"抗体 / antibody: {_clean(row['antibody']) or 'not recorded'}",
            f"连接子 / linker: {_clean(row['linker_name']) or 'not recorded'}",
            f"连接子类型 / linker type: {_clean(row['linker_type'])}",
            f"载荷 / payload: {_clean(row['payload_name']) or 'not recorded'}",
            f"载荷类型 / payload class: {_clean(row['payload_class']) or 'not recorded'}",
            f"药物抗体比 / DAR: {row['dar'] if row['dar'] is not None else 'not recorded'}",
            f"适应证 / indication: {_clean(row['indication']) or 'not recorded'}",
            f"研发状态 / development status: {_clean(row['development_status'])}",
            f"企业 / company: {_clean(row['company']) or 'not recorded'}",
        ]
        metadata = {
            "adc_ids": [str(row["adc_id"])],
            "adc_names": [str(row["adc_name"])],
            "targets": [str(row["target"])],
            "payloads": [str(row["payload_name"])] if row["payload_name"] else [],
            "aliases": aliases,
            "review_status": str(row["data_review_status"]),
        }
        documents.append(
            RetrievalDocument(
                retrieval_document_id=f"adc_profile:{row['adc_id']}",
                source_type="adc_profile",
                source_record_id=str(row["adc_id"]),
                title=f"ADC profile: {row['adc_name']}",
                content="\n".join(lines),
                source_url=str(row["source_url"] or ""),
                metadata=metadata,
            )
        )
    return documents


def _pubmed_documents(connection) -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for row in connection.execute("SELECT * FROM documents ORDER BY document_id"):
        entities = _linked_entities(connection, "document", str(row["document_id"]))
        try:
            topic_rows = connection.execute(
                "SELECT topic FROM literature_topics WHERE document_id=? ORDER BY topic",
                (row["document_id"],),
            ).fetchall()
            literature_topics = [str(item["topic"]) for item in topic_rows]
        except Exception:
            # Older/demo databases have no public topic table.
            literature_topics = []
        title = _clean(row["title"])
        abstract = _clean(row["abstract"])
        content = "\n".join(
            part
            for part in (
                f"Title: {title}",
                f"Abstract: {abstract}" if abstract else "",
                f"Journal: {_clean(row['journal'])}" if row["journal"] else "",
                f"Publication date: {_clean(row['publication_date'])}"
                if row["publication_date"]
                else "",
            )
            if part
        )
        metadata = {
            "adc_ids": entities.get("adc", []),
            "adc_names": entities.get("adc_names", []),
            "targets": entities.get("target", []),
            "payloads": entities.get("payload", []),
            "journal": row["journal"],
            "publication_date": row["publication_date"],
            "doi": row["doi"],
            "literature_topics": literature_topics,
        }
        documents.append(
            RetrievalDocument(
                retrieval_document_id=str(row["document_id"]),
                source_type="pubmed",
                source_record_id=str(row["source_record_id"]),
                title=title,
                content=content,
                source_url=str(row["source_url"]),
                metadata=metadata,
            )
        )
    return documents


def _trial_documents(connection) -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for row in connection.execute("SELECT * FROM trials ORDER BY nct_id"):
        entities = _linked_entities(connection, "trial", str(row["nct_id"]))
        title = _clean(row["brief_title"])
        phases = _json_list(row["phases_json"])
        conditions = _json_list(row["conditions_json"])
        interventions = _json_list(row["interventions_json"])
        outcomes = _json_list(row["primary_outcomes_json"])
        lines = [
            f"Clinical trial: {row['nct_id']}",
            f"Brief title: {title}",
            f"Official title: {_clean(row['official_title'])}" if row["official_title"] else "",
            f"Recruitment status: {_clean(row['overall_status'])}" if row["overall_status"] else "",
            f"Phase: {', '.join(phases)}" if phases else "",
            f"Conditions: {', '.join(conditions)}" if conditions else "",
            f"Interventions: {', '.join(interventions)}" if interventions else "",
            f"Sponsor: {_clean(row['sponsor'])}" if row["sponsor"] else "",
            f"Enrollment: {row['enrollment']}" if row["enrollment"] is not None else "",
            f"Primary outcomes: {'; '.join(outcomes)}" if outcomes else "",
            f"Start date: {_clean(row['start_date'])}" if row["start_date"] else "",
            f"Completion date: {_clean(row['completion_date'])}" if row["completion_date"] else "",
        ]
        metadata = {
            "adc_ids": entities.get("adc", []),
            "adc_names": entities.get("adc_names", []),
            "targets": entities.get("target", []),
            "payloads": entities.get("payload", []),
            "nct_id": str(row["nct_id"]),
            "status": row["overall_status"],
            "phases": phases,
            "conditions": conditions,
            "interventions": interventions,
        }
        documents.append(
            RetrievalDocument(
                retrieval_document_id=f"trial:{row['nct_id']}",
                source_type="clinical_trial",
                source_record_id=str(row["nct_id"]),
                title=title,
                content="\n".join(line for line in lines if line),
                source_url=str(row["source_url"]),
                metadata=metadata,
            )
        )
    return documents


def build_retrieval_documents(database_path: Path = DEFAULT_DATABASE_PATH) -> list[RetrievalDocument]:
    create_database(database_path)
    with closing(connect(database_path)) as connection:
        return [
            *_adc_documents(connection),
            *_pubmed_documents(connection),
            *_trial_documents(connection),
        ]


def split_text(text: str, *, max_chars: int = 1200, overlap_chars: int = 160) -> list[str]:
    if max_chars <= overlap_chars:
        raise ValueError("max_chars must be greater than overlap_chars")
    text = text.strip()
    if not text:
        return []
    raw_units = [
        unit.strip()
        for unit in re.split(r"(?<=[.!?。！？])\s+|\n+", text)
        if unit.strip()
    ]
    units: list[str] = []
    step = max_chars - overlap_chars
    for unit in raw_units:
        if len(unit) <= max_chars:
            units.append(unit)
            continue
        start = 0
        while start < len(unit):
            units.append(unit[start : start + max_chars])
            start += step
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n{unit}".strip() if current else unit
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        available_overlap = max_chars - len(unit) - 1
        if current and available_overlap > 0:
            overlap = current[-min(overlap_chars, available_overlap) :].lstrip()
            current = f"{overlap}\n{unit}".strip()
        else:
            current = unit
    if current:
        chunks.append(current)
    return chunks


def chunk_documents(
    documents: list[RetrievalDocument],
    *,
    max_chars: int = 1200,
    overlap_chars: int = 160,
) -> list[TextChunk]:
    chunks: list[TextChunk] = []
    for document in documents:
        pieces = split_text(
            document.content,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        for index, content in enumerate(pieces):
            chunks.append(
                TextChunk(
                    chunk_id=f"{document.retrieval_document_id}#chunk-{index:03d}",
                    retrieval_document_id=document.retrieval_document_id,
                    chunk_index=index,
                    title=document.title,
                    content=content,
                    metadata={
                        **document.metadata,
                        "source_type": document.source_type,
                        "source_record_id": document.source_record_id,
                        "source_url": document.source_url,
                    },
                )
            )
    return chunks


def persist_retrieval_corpus(
    database_path: Path,
    documents: list[RetrievalDocument],
    chunks: list[TextChunk],
) -> None:
    create_database(database_path)
    with closing(connect(database_path)) as connection, connection:
        connection.execute("DELETE FROM text_chunks_fts")
        connection.execute("DELETE FROM text_chunks")
        connection.execute("DELETE FROM retrieval_documents")
        connection.executemany(
            """
            INSERT INTO retrieval_documents (
                retrieval_document_id, source_type, source_record_id, title,
                content, source_url, metadata_json, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.retrieval_document_id,
                    item.source_type,
                    item.source_record_id,
                    item.title,
                    item.content,
                    item.source_url,
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                    _retrieval_document_hash(item),
                )
                for item in documents
            ],
        )
        connection.executemany(
            """
            INSERT INTO text_chunks (
                chunk_id, retrieval_document_id, chunk_index, title, content,
                char_count, metadata_json, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.chunk_id,
                    item.retrieval_document_id,
                    item.chunk_index,
                    item.title,
                    item.content,
                    len(item.content),
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                    _text_chunk_hash(item),
                )
                for item in chunks
            ],
        )
        connection.executemany(
            "INSERT INTO text_chunks_fts (chunk_id, title, content, entities) VALUES (?, ?, ?, ?)",
            [
                (
                    item.chunk_id,
                    item.title,
                    item.content,
                    " ".join(
                        str(value)
                        for key in ("adc_names", "targets", "payloads", "aliases")
                        for value in item.metadata.get(key, [])
                    ),
                )
                for item in chunks
            ],
        )


def _retrieval_document_hash(item: RetrievalDocument) -> str:
    return _hash(
        json.dumps(
            {
                "source_type": item.source_type,
                "source_record_id": item.source_record_id,
                "title": item.title,
                "content": item.content,
                "source_url": item.source_url,
                "metadata": item.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _text_chunk_hash(item: TextChunk) -> str:
    return _hash(
        json.dumps(
            {
                "title": item.title,
                "content": item.content,
                "metadata": item.metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def persist_retrieval_corpus_incremental(
    database_path: Path,
    documents: list[RetrievalDocument],
    chunks: list[TextChunk],
) -> dict[str, object]:
    """Replace only changed retrieval documents and their dependent chunks."""
    create_database(database_path)
    document_by_id = {item.retrieval_document_id: item for item in documents}
    chunks_by_document: dict[str, list[TextChunk]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(chunk.retrieval_document_id, []).append(chunk)

    with closing(connect(database_path)) as connection, connection:
        existing = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT retrieval_document_id, content_hash FROM retrieval_documents"
            ).fetchall()
        }
        incoming_hashes = {
            document_id: _retrieval_document_hash(document)
            for document_id, document in document_by_id.items()
        }
        added = sorted(set(incoming_hashes) - set(existing))
        deleted = sorted(set(existing) - set(incoming_hashes))
        updated = sorted(
            document_id
            for document_id in set(existing) & set(incoming_hashes)
            if existing[document_id] != incoming_hashes[document_id]
        )
        unchanged = sorted(set(existing) & set(incoming_hashes) - set(updated))
        affected = set(added) | set(updated) | set(deleted)
        if affected:
            old_chunk_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT chunk_id, retrieval_document_id FROM text_chunks"
                ).fetchall()
                if str(row[1]) in affected
            ]
            connection.executemany(
                "DELETE FROM text_chunks_fts WHERE chunk_id = ?",
                [(chunk_id,) for chunk_id in old_chunk_ids],
            )
            connection.executemany(
                "DELETE FROM retrieval_documents WHERE retrieval_document_id = ?",
                [(document_id,) for document_id in sorted(affected)],
            )

        changed_documents = [
            document_by_id[document_id] for document_id in added + updated
        ]
        connection.executemany(
            """
            INSERT INTO retrieval_documents (
                retrieval_document_id, source_type, source_record_id, title,
                content, source_url, metadata_json, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.retrieval_document_id,
                    item.source_type,
                    item.source_record_id,
                    item.title,
                    item.content,
                    item.source_url,
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                    incoming_hashes[item.retrieval_document_id],
                )
                for item in changed_documents
            ],
        )
        changed_chunks = [
            chunk
            for document_id in added + updated
            for chunk in chunks_by_document.get(document_id, [])
        ]
        connection.executemany(
            """
            INSERT INTO text_chunks (
                chunk_id, retrieval_document_id, chunk_index, title, content,
                char_count, metadata_json, content_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.chunk_id,
                    item.retrieval_document_id,
                    item.chunk_index,
                    item.title,
                    item.content,
                    len(item.content),
                    json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
                    _text_chunk_hash(item),
                )
                for item in changed_chunks
            ],
        )
        connection.executemany(
            "INSERT INTO text_chunks_fts (chunk_id, title, content, entities) VALUES (?, ?, ?, ?)",
            [
                (
                    item.chunk_id,
                    item.title,
                    item.content,
                    " ".join(
                        str(value)
                        for key in ("adc_names", "targets", "payloads", "aliases")
                        for value in item.metadata.get(key, [])
                    ),
                )
                for item in changed_chunks
            ],
        )
    return {
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "added_document_ids": added,
        "updated_document_ids": updated,
        "deleted_document_ids": deleted,
        "unchanged_document_count": len(unchanged),
        "affected_document_count": len(affected),
        "rewritten_chunk_count": len(changed_chunks),
    }


def retrieval_corpus_version(database_path: Path) -> str:
    """Return a deterministic version for exactly the rows consumed by dense search."""
    digest = hashlib.sha256()
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            "SELECT chunk_id, content_hash FROM text_chunks ORDER BY chunk_id"
        ).fetchall()
    for row in rows:
        digest.update(str(row[0]).encode("utf-8"))
        digest.update(b"\x1f")
        digest.update(str(row[1]).encode("utf-8"))
        digest.update(b"\n")
    return "corpus_" + digest.hexdigest()


def build_and_persist_corpus(
    database_path: Path = DEFAULT_DATABASE_PATH,
    *,
    max_chars: int = 1200,
    overlap_chars: int = 160,
) -> tuple[int, int]:
    documents = build_retrieval_documents(database_path)
    chunks = chunk_documents(
        documents,
        max_chars=max_chars,
        overlap_chars=overlap_chars,
    )
    persist_retrieval_corpus_incremental(database_path, documents, chunks)
    return len(documents), len(chunks)
