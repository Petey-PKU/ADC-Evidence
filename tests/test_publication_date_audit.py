from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path

from scripts.audit_public_dataset import _late_publication_dates
from tests.support import WorkspaceTemporaryDirectory


def article(*, pmid: str = "1", electronic: str = "", history: str = "") -> str:
    return (f"<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>"
            f"{electronic}</Article></MedlineCitation><PubmedData><History>"
            f"{history}</History></PubmedData></PubmedArticle>")


def history_date(status: str, month: str = "7", day: str = "1") -> str:
    return (f'<PubMedPubDate PubStatus="{status}"><Year>2026</Year>'
            f"<Month>{month}</Month><Day>{day}</Day></PubMedPubDate>")


class PublicationDateAuditTests(unittest.TestCase):
    def run_audit(self, directory: Path, xml: str, *, checksum=None, raw_root=True):
        path = directory / "fixture.xml"
        raw = ("<PubmedArticleSet>" + xml + "</PubmedArticleSet>").encode()
        path.write_bytes(raw)
        with sqlite3.connect(":memory:") as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("CREATE TABLE documents (source, source_record_id, publication_date, raw_path, checksum)")
            connection.execute("INSERT INTO documents VALUES (?,?,?,?,?)", (
                "pubmed", "1", "2026-Oct", str(path.resolve()),
                checksum if checksum is not None else hashlib.sha256(raw).hexdigest(),
            ))
            return _late_publication_dates(
                connection, as_of=dt.date(2026, 9, 30),
                raw_root=directory if raw_root is True else raw_root,
            )

    def test_electronic_and_processing_dates_are_separate_and_not_gold(self):
        electronic = ('<ArticleDate DateType="Electronic"><Year>2026</Year>'
                      '<Month>07</Month><Day>20</Day></ArticleDate>')
        with WorkspaceTemporaryDirectory() as tmp:
            result = self.run_audit(Path(tmp), article(electronic=electronic, history=history_date("entrez")))
        row = result["records"][0]
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(row["reason"], "electronic_publication_before_cutoff")
        self.assertEqual(row["status"], "candidate_pending_review")
        self.assertEqual({d["kind"] for d in row["dates"]}, {"article:Electronic", "history:entrez"})
        self.assertNotIn(tmp, json.dumps(result))

    def test_indexing_alone_and_inverted_chronology_remain_flagged(self):
        with WorkspaceTemporaryDirectory() as tmp:
            result = self.run_audit(Path(tmp), article(history=history_date("pubmed", "6") + history_date("accepted", "9")))
        row = result["records"][0]
        self.assertEqual(row["reason"], "indexing_before_cutoff_only")
        self.assertEqual(row["chronology_flags"], ["acceptance_after_publication_or_indexing"])

    def test_received_and_accepted_are_not_publication_evidence(self):
        with WorkspaceTemporaryDirectory() as tmp:
            result = self.run_audit(Path(tmp), article(history=history_date("accepted") + history_date("received")))
        self.assertEqual(result["records"][0]["reason"], "no_pre_cutoff_publication_or_indexing_evidence")

    def test_invalid_dates_and_post_cutoff_dates_do_not_pass(self):
        with WorkspaceTemporaryDirectory() as tmp:
            result = self.run_audit(Path(tmp), article(history=history_date("epublish", "10") + history_date("pubmed", "2", "30")))
        row = result["records"][0]
        self.assertEqual(row["reason"], "no_pre_cutoff_publication_or_indexing_evidence")
        self.assertEqual(row["invalid_date_count"], 1)

    def test_untrusted_or_unbound_raw_files_fail_closed(self):
        with WorkspaceTemporaryDirectory() as tmp:
            directory = Path(tmp)
            cases = [
                (article(), {"raw_root": None}, "raw_root_not_supplied"),
                (article(), {"raw_root": directory / "different-root"}, "raw_path_outside_allowed_root"),
                (article(), {"checksum": "0" * 64}, "raw_checksum_mismatch"),
                (article(pmid="2"), {}, "pmid_not_unique_in_raw"),
                (article() + article(), {}, "pmid_not_unique_in_raw"),
                ("<broken>", {}, "invalid_xml"),
            ]
            for xml, kwargs, reason in cases:
                with self.subTest(reason=reason):
                    row = self.run_audit(directory, xml, **kwargs)["records"][0]
                    self.assertEqual(row["reason"], reason)
                    self.assertEqual(row["status"], "unknown")
                    self.assertNotIn("dates", row)

    def test_cli_applies_requested_as_of_instead_of_default(self):
        with WorkspaceTemporaryDirectory() as tmp:
            database = Path(tmp) / "fixture.db"
            output = Path(tmp) / "audit.json"
            with sqlite3.connect(database) as connection:
                connection.executescript("""
                    CREATE TABLE adcs (adc_id TEXT PRIMARY KEY);
                    CREATE TABLE documents (document_id TEXT PRIMARY KEY, publication_date TEXT);
                    CREATE TABLE trials (nct_id TEXT PRIMARY KEY);
                    CREATE TABLE entity_links (entity_type, entity_id, source_record_type, source_record_id, match_method);
                    INSERT INTO documents VALUES ('fixture', '2026-Oct');
                """)
            root = Path(__file__).resolve().parents[1]
            subprocess.run([
                sys.executable, str(root / "scripts/audit_public_dataset.py"),
                "--database", str(database), "--output", str(output), "--as-of", "2026-12-31",
            ], cwd=root, check=True, capture_output=True, text=True)
            result = json.loads(output.read_text(encoding="utf-8"))
        dates = result["record_date_quality"]["documents.publication_date"]
        self.assertEqual(dates["as_of"], "2026-12-31")
        self.assertEqual(dates["after_as_of_count"], 0)


if __name__ == "__main__":
    unittest.main()
