from __future__ import annotations
from tests.support import WorkspaceTemporaryDirectory

import json
import os
import sqlite3
import unittest
from unittest import mock
from contextlib import closing
from pathlib import Path

from adc_evidence.backup import sha256_file
from adc_evidence.config import DEFAULT_SEED_PATH
from adc_evidence.database import connect, create_database, initialize_database
from adc_evidence.rag.documents import (
    build_retrieval_documents,
    chunk_documents,
    persist_retrieval_corpus_incremental,
)
from adc_evidence.rag.vector_index import build_vector_index, load_vector_index
from adc_evidence.refresh import (
    build_release_manifest,
    execute_refresh,
    publish_staged_assets,
)
from adc_evidence.refresh_ops import RefreshLock, evaluate_refresh_gates, retry_call
from adc_evidence.repository import (
    finish_ingestion_run,
    finish_source_run,
    recover_stale_ingestion_runs,
    start_ingestion_run,
    start_source_run,
)


class RefreshOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = WorkspaceTemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "adc.db"
        create_database(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _start_run(self, run_id: str) -> None:
        start_ingestion_run(self.database, run_id, f"{run_id}-start", {})

    def test_recover_stale_ingestion_run_marks_sources_terminal(self) -> None:
        run_id = "stale-run"
        start_ingestion_run(self.database, run_id, "2020-01-01T00:00:00+00:00", {})
        start_source_run(self.database, run_id, "clinicaltrials", "2020-01-01T00:00:00+00:00")

        recovered = recover_stale_ingestion_runs(
            self.database,
            now="2020-01-02T00:00:00+00:00",
            stale_after_seconds=3600,
        )

        self.assertEqual(recovered, [run_id])
        with closing(connect(self.database)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM ingestion_runs WHERE run_id = ?", (run_id,)
                ).fetchone()[0],
                "failed",
            )
            self.assertEqual(
                connection.execute(
                    "SELECT status FROM ingestion_source_runs WHERE run_id = ?", (run_id,)
                ).fetchone()[0],
                "failed",
            )

    def _source_run(
        self,
        run_id: str,
        *,
        status: str,
        record_ids: list[str],
        is_complete: bool,
        details: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self._start_run(run_id)
        start_source_run(self.database, run_id, "adcdb", f"{run_id}-start")
        result = finish_source_run(
            self.database,
            run_id,
            "adcdb",
            f"{run_id}-finish",
            status=status,
            attempts=1,
            expected_count=2,
            record_ids=record_ids,
            is_complete=is_complete,
            details=details,
        )
        finish_ingestion_run(
            self.database,
            run_id,
            f"{run_id}-finish",
            status,
            {},
        )
        return result

    def test_retry_uses_bounded_exponential_backoff(self) -> None:
        attempts = 0
        delays: list[float] = []

        def operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary")
            return "ok"

        value, used_attempts = retry_call(
            operation,
            max_attempts=3,
            base_delay_seconds=0.5,
            sleep=delays.append,
        )
        self.assertEqual(value, "ok")
        self.assertEqual(used_attempts, 3)
        self.assertEqual(delays, [0.5, 1.0])

    def test_refresh_lock_prevents_concurrent_owner_and_releases(self) -> None:
        lock_path = self.root / "refresh.lock"
        with RefreshLock(lock_path):
            self.assertTrue(lock_path.exists())
            with self.assertRaisesRegex(RuntimeError, "Another refresh"):
                RefreshLock(lock_path).acquire()
        self.assertFalse(lock_path.exists())
        with RefreshLock(lock_path):
            self.assertTrue(lock_path.exists())

    def test_missing_records_require_two_complete_source_snapshots(self) -> None:
        self._source_run(
            "run-1",
            status="complete",
            record_ids=["one", "two"],
            is_complete=True,
        )
        partial = self._source_run(
            "run-2",
            status="partial",
            record_ids=["one"],
            is_complete=False,
        )
        complete = self._source_run(
            "run-3",
            status="complete",
            record_ids=["one"],
            is_complete=True,
        )

        self.assertEqual(partial["missing_record_ids"], [])
        self.assertEqual(complete["missing_record_ids"], ["two"])
        gates = evaluate_refresh_gates(
            self.database,
            "run-3",
            required_sources=("adcdb",),
            max_count_drop_ratio=0.25,
            max_missing_records=0,
        )
        self.assertFalse(gates["passed"])
        failed = {
            check["name"]
            for check in gates["checks"]
            if check["blocking"] and not check["passed"]
        }
        self.assertEqual(failed, {"count_anomaly:adcdb", "missing_records"})

    def test_planned_truncation_disables_missing_detection_without_failing(self) -> None:
        self._start_run("pubmed-run")
        start_source_run(self.database, "pubmed-run", "pubmed", "start")
        finish_source_run(
            self.database,
            "pubmed-run",
            "pubmed",
            "finish",
            status="complete",
            attempts=1,
            expected_count=1000,
            record_ids=["1", "2"],
            is_complete=False,
            details={"planned_truncation": True},
        )
        finish_ingestion_run(
            self.database,
            "pubmed-run",
            "finish",
            "complete",
            {},
        )
        gates = evaluate_refresh_gates(
            self.database,
            "pubmed-run",
            required_sources=("pubmed",),
        )
        self.assertTrue(gates["passed"])
        scope_gate = next(
            check
            for check in gates["checks"]
            if check["name"] == "missing_detection_scope:pubmed"
        )
        self.assertFalse(scope_gate["blocking"])

    def test_empty_complete_response_is_blocked_as_count_drop_and_missing(self) -> None:
        self._source_run(
            "baseline",
            status="complete",
            record_ids=["one"],
            is_complete=True,
        )
        result = self._source_run(
            "empty",
            status="complete",
            record_ids=[],
            is_complete=True,
        )
        gates = evaluate_refresh_gates(
            self.database,
            "empty",
            required_sources=("adcdb",),
        )
        self.assertEqual(result["missing_record_ids"], ["one"])
        self.assertFalse(gates["passed"])


class IncrementalCorpusTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = WorkspaceTemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.database = self.root / "adc.db"
        initialize_database(self.database, DEFAULT_SEED_PATH)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _persist(self) -> dict[str, object]:
        documents = build_retrieval_documents(self.database)
        chunks = chunk_documents(documents)
        return persist_retrieval_corpus_incremental(
            self.database,
            documents,
            chunks,
        )

    def test_only_affected_documents_and_chunks_are_rewritten(self) -> None:
        first = self._persist()
        second = self._persist()
        with closing(connect(self.database)) as connection, connection:
            connection.execute(
                "UPDATE adcs SET target = 'HER2-updated' WHERE adc_id = 'adc_001'"
            )
        third = self._persist()

        self.assertEqual(first["added_document_ids"], [
            f"adc_profile:adc_{number:03d}" for number in range(1, 11)
        ])
        self.assertEqual(second["affected_document_count"], 0)
        self.assertEqual(third["updated_document_ids"], ["adc_profile:adc_001"])
        self.assertEqual(third["rewritten_chunk_count"], 1)
        with closing(connect(self.database)) as connection:
            chunk_count = connection.execute("SELECT COUNT(*) FROM text_chunks").fetchone()[0]
            fts_count = connection.execute("SELECT COUNT(*) FROM text_chunks_fts").fetchone()[0]
        self.assertEqual(chunk_count, fts_count)

    def test_dense_index_rejects_a_different_corpus_version(self) -> None:
        self._persist()
        index = self.root / "index"
        build_vector_index(
            database_path=self.database,
            index_path=index,
            backend="hashing",
            dimension=64,
        )
        load_vector_index(index, database_path=self.database)
        with closing(connect(self.database)) as connection, connection:
            connection.execute(
                "UPDATE adcs SET target = 'changed' WHERE adc_id = 'adc_001'"
            )
        self._persist()
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            load_vector_index(index, database_path=self.database)


class RefreshReleaseTests(unittest.TestCase):
    def test_offline_staged_release_publishes_database_index_and_manifest(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database = root / "live" / "adc.db"
            index = root / "live" / "index"
            result = execute_refresh(
                live_database=database,
                live_index=index,
                staging_root=root / "staging",
                backup_directory=root / "backups",
                release_directory=root / "releases",
                lock_path=root / "refresh.lock",
                embedding_backend="hashing",
                embedding_dimension=64,
                skip_adcdb=True,
                skip_trials=True,
                skip_pubmed=True,
                source_retry_delay=0,
                refresh_id="offline-release",
            )

            self.assertTrue(result["published"])
            self.assertTrue(database.is_file())
            self.assertTrue((index / "manifest.json").is_file())
            manifest_path = Path(str(result["manifest_path"]))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "published")
            self.assertEqual(manifest["database"]["sha256"], sha256_file(database))
            load_vector_index(index, database_path=database)

    def test_rejected_stage_does_not_change_live_assets(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            database = root / "live" / "adc.db"
            index = root / "live" / "index"
            initialize_database(database, DEFAULT_SEED_PATH)
            documents = build_retrieval_documents(database)
            chunks = chunk_documents(documents)
            persist_retrieval_corpus_incremental(database, documents, chunks)
            build_vector_index(
                database_path=database,
                index_path=index,
                backend="hashing",
                dimension=64,
            )
            original_database_hash = sha256_file(database)
            original_index_hash = sha256_file(index / "manifest.json")

            def failed_source(args) -> dict[str, object]:
                start_ingestion_run(args.database, args.run_id, "start", {})
                start_source_run(args.database, args.run_id, "adcdb", "start")
                finish_source_run(
                    args.database,
                    args.run_id,
                    "adcdb",
                    "finish",
                    status="failed",
                    attempts=3,
                    expected_count=10,
                    is_complete=False,
                    error_text="offline failure fixture",
                )
                finish_ingestion_run(
                    args.database,
                    args.run_id,
                    "finish",
                    "partial",
                    {},
                    "offline failure fixture",
                )
                return {"run_id": args.run_id, "status": "partial"}

            result = execute_refresh(
                live_database=database,
                live_index=index,
                staging_root=root / "staging",
                backup_directory=root / "backups",
                release_directory=root / "releases",
                lock_path=root / "refresh.lock",
                embedding_backend="hashing",
                skip_trials=True,
                skip_pubmed=True,
                refresh_id="rejected-release",
                pipeline_runner=failed_source,
            )
            self.assertFalse(result["published"])
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(sha256_file(database), original_database_hash)
            self.assertEqual(sha256_file(index / "manifest.json"), original_index_hash)
            self.assertFalse((root / "backups").exists())

    def test_publish_failure_restores_previous_database_and_index(self) -> None:
        with WorkspaceTemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            live_database = root / "live" / "adc.db"
            live_index = root / "live" / "index"
            staged_database = root / "stage" / "adc.db"
            staged_index = root / "stage" / "index"
            initialize_database(live_database, DEFAULT_SEED_PATH)
            initialize_database(staged_database, DEFAULT_SEED_PATH)
            with closing(connect(staged_database)) as connection, connection:
                connection.execute(
                    "UPDATE adcs SET target = 'new-release' WHERE adc_id = 'adc_001'"
                )
            for database, index in (
                (live_database, live_index),
                (staged_database, staged_index),
            ):
                documents = build_retrieval_documents(database)
                chunks = chunk_documents(documents)
                summary = persist_retrieval_corpus_incremental(
                    database,
                    documents,
                    chunks,
                )
                build_vector_index(
                    database_path=database,
                    index_path=index,
                    backend="hashing",
                    dimension=64,
                )
            old_index_hash = sha256_file(live_index / "manifest.json")
            manifest = build_release_manifest(
                release_id="rollback-release",
                run_id="rollback-run",
                database_path=staged_database,
                index_path=staged_index,
                gate_report={"passed": True},
                corpus_summary=summary,
            )
            real_replace = os.replace
            replace_count = 0

            def fail_index_promotion(source, destination) -> None:
                nonlocal replace_count
                replace_count += 1
                if replace_count == 3:
                    raise OSError("simulated index promotion failure")
                real_replace(source, destination)

            with mock.patch(
                "adc_evidence.refresh.os.replace",
                side_effect=fail_index_promotion,
            ):
                with self.assertRaisesRegex(OSError, "simulated"):
                    publish_staged_assets(
                        staged_database=staged_database,
                        staged_index=staged_index,
                        live_database=live_database,
                        live_index=live_index,
                        backup_directory=root / "backups",
                        release_directory=root / "releases",
                        release_manifest=manifest,
                    )

            with closing(connect(live_database)) as connection:
                target = connection.execute(
                    "SELECT target FROM adcs WHERE adc_id = 'adc_001'"
                ).fetchone()[0]
            self.assertEqual(target, "HER2")
            self.assertEqual(sha256_file(live_index / "manifest.json"), old_index_hash)


if __name__ == "__main__":
    unittest.main()
