from __future__ import annotations

import csv
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from adc_evidence.models import ADCRecord


FACTS_SCHEMA_VERSION = "0.6-facts-v1"
SCHEMA_VERSION = "0.6-refresh-v1"
REVIEW_SCHEMA_VERSION = "0.6-benchmark-review-v2"
SCHEMA_VERSIONS = (FACTS_SCHEMA_VERSION, SCHEMA_VERSION, REVIEW_SCHEMA_VERSION)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS adcs (
    adc_id TEXT PRIMARY KEY,
    adc_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    target TEXT NOT NULL,
    antibody TEXT,
    linker_name TEXT,
    linker_type TEXT NOT NULL,
    payload_name TEXT,
    payload_class TEXT,
    dar REAL CHECK (dar IS NULL OR (dar >= 0 AND dar <= 20)),
    indication TEXT,
    development_status TEXT NOT NULL,
    company TEXT,
    source_url TEXT,
    data_review_status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS adc_aliases (
    alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
    adc_id TEXT NOT NULL,
    alias TEXT NOT NULL COLLATE NOCASE,
    FOREIGN KEY (adc_id) REFERENCES adcs(adc_id) ON DELETE CASCADE,
    UNIQUE (adc_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_adcs_target ON adcs(target);
CREATE INDEX IF NOT EXISTS idx_adcs_payload ON adcs(payload_name);
CREATE INDEX IF NOT EXISTS idx_aliases_alias ON adc_aliases(alias);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    summary_json TEXT,
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS ingestion_source_runs (
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('running', 'complete', 'partial', 'failed', 'skipped')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    expected_count INTEGER CHECK (expected_count IS NULL OR expected_count >= 0),
    collected_count INTEGER NOT NULL DEFAULT 0 CHECK (collected_count >= 0),
    is_complete INTEGER NOT NULL DEFAULT 0 CHECK (is_complete IN (0, 1)),
    error_text TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, source),
    FOREIGN KEY (run_id) REFERENCES ingestion_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS source_run_records (
    run_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    snapshot_id TEXT,
    PRIMARY KEY (run_id, source, source_record_id),
    FOREIGN KEY (run_id, source)
        REFERENCES ingestion_source_runs(run_id, source) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id)
        REFERENCES source_snapshots(snapshot_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_source_runs_source
    ON ingestion_source_runs(source, finished_at, status, is_complete);
CREATE INDEX IF NOT EXISTS idx_source_run_records_source
    ON source_run_records(source, source_record_id, run_id);

CREATE TABLE IF NOT EXISTS source_records (
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    dataset_version TEXT,
    PRIMARY KEY (source, source_record_id)
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    title TEXT NOT NULL,
    abstract TEXT,
    authors_json TEXT NOT NULL,
    journal TEXT,
    publication_date TEXT,
    doi TEXT,
    source_url TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    UNIQUE (source, source_record_id)
);

CREATE TABLE IF NOT EXISTS trials (
    nct_id TEXT PRIMARY KEY,
    brief_title TEXT NOT NULL,
    official_title TEXT,
    overall_status TEXT,
    phases_json TEXT NOT NULL,
    conditions_json TEXT NOT NULL,
    interventions_json TEXT NOT NULL,
    sponsor TEXT,
    enrollment INTEGER,
    start_date TEXT,
    completion_date TEXT,
    last_update_date TEXT,
    primary_outcomes_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    checksum TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_links (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    source_record_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    matched_alias TEXT NOT NULL,
    match_method TEXT NOT NULL,
    PRIMARY KEY (
        entity_type, entity_id, source_record_type,
        source_record_id, matched_alias
    )
);

CREATE TABLE IF NOT EXISTS external_identifiers (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id, source, external_id)
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    value TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    review_status TEXT NOT NULL,
    extractor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (entity_type, entity_id, normalized_alias, source)
);

CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source);
CREATE INDEX IF NOT EXISTS idx_trials_status ON trials(overall_status);
CREATE INDEX IF NOT EXISTS idx_links_entity ON entity_links(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_links_record ON entity_links(source_record_type, source_record_id);
CREATE INDEX IF NOT EXISTS idx_evidence_subject ON evidence(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source, source_record_id);

CREATE TABLE IF NOT EXISTS retrieval_documents (
    retrieval_document_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE (source_type, source_record_id)
);

CREATE TABLE IF NOT EXISTS text_chunks (
    chunk_id TEXT PRIMARY KEY,
    retrieval_document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (retrieval_document_id)
        REFERENCES retrieval_documents(retrieval_document_id) ON DELETE CASCADE,
    UNIQUE (retrieval_document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_retrieval_documents_source
    ON retrieval_documents(source_type, source_record_id);
CREATE INDEX IF NOT EXISTS idx_text_chunks_document
    ON text_chunks(retrieval_document_id, chunk_index);

CREATE TABLE IF NOT EXISTS review_items (
    item_id TEXT PRIMARY KEY,
    item_type TEXT NOT NULL,
    evaluation_run_id TEXT NOT NULL DEFAULT 'legacy',
    question_id TEXT NOT NULL,
    category TEXT NOT NULL,
    question TEXT NOT NULL,
    expected_refusal INTEGER NOT NULL,
    expected_document_ids_json TEXT NOT NULL,
    system_status TEXT NOT NULL,
    system_output TEXT NOT NULL,
    system_document_ids_json TEXT NOT NULL,
    backend TEXT NOT NULL,
    model_name TEXT NOT NULL DEFAULT 'unknown',
    metadata_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS expert_reviews (
    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    reviewer TEXT NOT NULL,
    question_verdict TEXT NOT NULL,
    evidence_verdict TEXT NOT NULL,
    answer_verdict TEXT NOT NULL,
    citation_verdict TEXT NOT NULL DEFAULT 'not_applicable',
    completeness_verdict TEXT NOT NULL DEFAULT 'not_applicable',
    refusal_verdict TEXT NOT NULL,
    reviewer_slot TEXT NOT NULL DEFAULT 'primary',
    review_origin TEXT,
    severity TEXT NOT NULL,
    error_categories_json TEXT NOT NULL,
    notes TEXT NOT NULL,
    item_content_hash TEXT NOT NULL,
    reviewed_at TEXT NOT NULL,
    FOREIGN KEY (item_id) REFERENCES review_items(item_id) ON DELETE CASCADE,
    UNIQUE (item_id, reviewer)
);

CREATE INDEX IF NOT EXISTS idx_review_items_type
    ON review_items(item_type, category);
CREATE INDEX IF NOT EXISTS idx_expert_reviews_item
    ON expert_reviews(item_id, reviewer);

CREATE TABLE IF NOT EXISTS schema_versions (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    source_updated_at TEXT,
    source_url TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    dataset_version TEXT,
    ingestion_run_id TEXT,
    parser_version TEXT NOT NULL,
    FOREIGN KEY (ingestion_run_id)
        REFERENCES ingestion_runs(run_id) ON DELETE SET NULL,
    UNIQUE (source, source_record_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_source_snapshots_record
    ON source_snapshots(source, source_record_id, fetched_at);
CREATE INDEX IF NOT EXISTS idx_source_snapshots_run
    ON source_snapshots(ingestion_run_id);

CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    normalized_value_json TEXT NOT NULL,
    display_value TEXT NOT NULL,
    value_type TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('current', 'superseded', 'conflicted')
    ),
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    review_status TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_subject
    ON facts(subject_type, subject_id, predicate, status);
CREATE INDEX IF NOT EXISTS idx_facts_value
    ON facts(subject_type, subject_id, predicate, value_hash);

CREATE TABLE IF NOT EXISTS fact_evidence (
    fact_evidence_id TEXT PRIMARY KEY,
    fact_id TEXT NOT NULL,
    snapshot_id TEXT,
    source TEXT NOT NULL,
    source_record_id TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    source_url TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    extractor TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    valid_to TEXT,
    is_current INTEGER NOT NULL CHECK (is_current IN (0, 1)),
    review_status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (fact_id) REFERENCES facts(fact_id) ON DELETE CASCADE,
    FOREIGN KEY (snapshot_id)
        REFERENCES source_snapshots(snapshot_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_fact_evidence_fact
    ON fact_evidence(fact_id, is_current);
CREATE INDEX IF NOT EXISTS idx_fact_evidence_source
    ON fact_evidence(
        source, source_record_id, is_current
    );
CREATE INDEX IF NOT EXISTS idx_fact_evidence_snapshot
    ON fact_evidence(snapshot_id);

CREATE TABLE IF NOT EXISTS change_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT,
    old_value_json TEXT NOT NULL,
    new_value_json TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    source TEXT,
    source_record_id TEXT,
    snapshot_id TEXT,
    review_required INTEGER NOT NULL CHECK (review_required IN (0, 1)),
    review_status TEXT NOT NULL,
    details_json TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    FOREIGN KEY (snapshot_id)
        REFERENCES source_snapshots(snapshot_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_change_events_subject
    ON change_events(subject_type, subject_id, detected_at);
CREATE INDEX IF NOT EXISTS idx_change_events_type
    ON change_events(event_type, severity, detected_at);

CREATE VIRTUAL TABLE IF NOT EXISTS text_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    title,
    content,
    entities,
    tokenize = 'unicode61 remove_diacritics 2'
);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_database(database_path: Path) -> None:
    with closing(connect(database_path)) as connection:
        with connection:
            connection.executescript(SCHEMA_SQL)
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(review_items)")
            }
            if "evaluation_run_id" not in columns:
                connection.execute(
                    "ALTER TABLE review_items ADD COLUMN "
                    "evaluation_run_id TEXT NOT NULL DEFAULT 'legacy'"
                )
            if "model_name" not in columns:
                connection.execute(
                    "ALTER TABLE review_items ADD COLUMN "
                    "model_name TEXT NOT NULL DEFAULT 'unknown'"
                )
            review_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(expert_reviews)")
            }
            if "citation_verdict" not in review_columns:
                connection.execute(
                    "ALTER TABLE expert_reviews ADD COLUMN "
                    "citation_verdict TEXT NOT NULL DEFAULT 'not_applicable'"
                )
            if "completeness_verdict" not in review_columns:
                connection.execute(
                    "ALTER TABLE expert_reviews ADD COLUMN "
                    "completeness_verdict TEXT NOT NULL DEFAULT 'not_applicable'"
                )
            if "reviewer_slot" not in review_columns:
                connection.execute(
                    "ALTER TABLE expert_reviews ADD COLUMN "
                    "reviewer_slot TEXT NOT NULL DEFAULT 'primary'"
                )
            if "review_origin" not in review_columns:
                connection.execute(
                    "ALTER TABLE expert_reviews ADD COLUMN review_origin TEXT"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_review_items_run "
                "ON review_items(evaluation_run_id, item_type)"
            )
            applied_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            connection.executemany(
                """
                INSERT OR IGNORE INTO schema_versions (version, applied_at)
                VALUES (?, ?)
                """,
                [(version, applied_at) for version in SCHEMA_VERSIONS],
            )


def load_seed_records(seed_path: Path) -> list[ADCRecord]:
    with seed_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
        return [ADCRecord.model_validate(row) for row in csv.DictReader(csv_file)]


def upsert_records(database_path: Path, records: Iterable[ADCRecord]) -> int:
    records = list(records)
    create_database(database_path)

    with closing(connect(database_path)) as connection:
        with connection:
            for record in records:
                values = record.model_dump(mode="json", exclude={"aliases"})
                connection.execute(
                    """
                    INSERT INTO adcs (
                        adc_id, adc_name, target, antibody, linker_name, linker_type,
                        payload_name, payload_class, dar, indication,
                        development_status, company, source_url, data_review_status
                    ) VALUES (
                        :adc_id, :adc_name, :target, :antibody, :linker_name,
                        :linker_type, :payload_name, :payload_class, :dar,
                        :indication, :development_status, :company, :source_url,
                        :data_review_status
                    )
                    ON CONFLICT(adc_id) DO UPDATE SET
                        adc_name = excluded.adc_name,
                        target = CASE
                            WHEN excluded.target IN ('unknown', 'Unknown', '') THEN adcs.target
                            ELSE excluded.target
                        END,
                        antibody = COALESCE(excluded.antibody, adcs.antibody),
                        linker_name = COALESCE(excluded.linker_name, adcs.linker_name),
                        linker_type = CASE
                            WHEN excluded.linker_type = 'unknown' THEN adcs.linker_type
                            ELSE excluded.linker_type
                        END,
                        payload_name = COALESCE(excluded.payload_name, adcs.payload_name),
                        payload_class = COALESCE(excluded.payload_class, adcs.payload_class),
                        dar = COALESCE(excluded.dar, adcs.dar),
                        indication = COALESCE(excluded.indication, adcs.indication),
                        development_status = CASE
                            WHEN excluded.development_status = 'unknown'
                                THEN adcs.development_status
                            ELSE excluded.development_status
                        END,
                        company = COALESCE(excluded.company, adcs.company),
                        source_url = COALESCE(excluded.source_url, adcs.source_url),
                        data_review_status = excluded.data_review_status
                    """,
                    values,
                )
                connection.executemany(
                    "INSERT OR IGNORE INTO adc_aliases (adc_id, alias) VALUES (?, ?)",
                    [(record.adc_id, alias) for alias in record.aliases],
                )

    return len(records)


def initialize_database(database_path: Path, seed_path: Path) -> int:
    return upsert_records(database_path, load_seed_records(seed_path))


def search_adcs(database_path: Path, query: str = "") -> list[dict[str, object]]:
    query = query.strip()
    wildcard = f"%{query}%"
    sql = """
        SELECT
            a.*,
            COALESCE(GROUP_CONCAT(aa.alias, ' | '), '') AS aliases
        FROM adcs AS a
        LEFT JOIN adc_aliases AS aa ON aa.adc_id = a.adc_id
        WHERE
            ? = ''
            OR a.adc_name LIKE ? COLLATE NOCASE
            OR a.target LIKE ? COLLATE NOCASE
            OR COALESCE(a.payload_name, '') LIKE ? COLLATE NOCASE
            OR EXISTS (
                SELECT 1
                FROM adc_aliases AS matched_alias
                WHERE matched_alias.adc_id = a.adc_id
                  AND matched_alias.alias LIKE ? COLLATE NOCASE
            )
        GROUP BY a.adc_id
        ORDER BY a.target, a.adc_name
    """
    with closing(connect(database_path)) as connection:
        rows = connection.execute(
            sql,
            (query, wildcard, wildcard, wildcard, wildcard),
        ).fetchall()
    return [dict(row) for row in rows]


def database_stats(database_path: Path) -> dict[str, int]:
    with closing(connect(database_path)) as connection:
        adc_count = connection.execute("SELECT COUNT(*) FROM adcs").fetchone()[0]
        target_count = connection.execute(
            "SELECT COUNT(DISTINCT target) FROM adcs"
        ).fetchone()[0]
        approved_count = connection.execute(
            "SELECT COUNT(*) FROM adcs WHERE development_status = 'approved'"
        ).fetchone()[0]
        document_count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        trial_count = connection.execute("SELECT COUNT(*) FROM trials").fetchone()[0]
        evidence_count = connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    return {
        "adc_count": adc_count,
        "target_count": target_count,
        "approved_count": approved_count,
        "document_count": document_count,
        "trial_count": trial_count,
        "evidence_count": evidence_count,
    }
