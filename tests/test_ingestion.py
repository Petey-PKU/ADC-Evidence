from tests.support import WorkspaceTemporaryDirectory
import unittest
from pathlib import Path

from adc_evidence.database import initialize_database
from adc_evidence.ingestion.adcdb import parse_adcdb_detail, parse_adcdb_search_results
from adc_evidence.ingestion.clinical_trials import parse_trials_page
from adc_evidence.ingestion.pubmed import parse_pubmed_xml
from adc_evidence.processing.normalize import EntityNormalizer, normalize_text
from adc_evidence.processing.standardize import (
    document_links_and_evidence,
    trial_links_and_evidence,
)
from adc_evidence.repository import (
    data_quality_metrics,
    upsert_documents,
    upsert_entity_links,
    upsert_evidence,
    upsert_trials,
)
from adc_evidence.config import DEFAULT_SEED_PATH


ADCDB_HTML = b"""
<table><tbody>
<tr><th>ADC ID</th><td colspan="6"><div>DRG0TEST1</div></td></tr>
<tr><th>ADC Name</th><td colspan="6"><div>Trastuzumab deruxtecan</div></td></tr>
<tr><th>Brand Name</th><td colspan="6"><div>Enhertu</div></td></tr>
<tr><th>Synonyms</th><td colspan="6"><div>DS-8201; T-DXd</div></td></tr>
<tr><th>Organization</th><td colspan="6"><div>Example Pharma</div></td></tr>
<tr><th>Drug Status</th><td colspan="6"><div><b>Approved in 2019</b></div></td></tr>
<tr><th>Drug-to-Antibody Ratio</th><td colspan="6"><div>8</div></td></tr>
<tr><th>Antibody Name</th><td colspan="5"><div>Trastuzumab</div></td></tr>
<tr><th>Antigen Name</th><td colspan="5"><div>erbB-2 (HER2)</div></td></tr>
<tr><th>Payload Name</th><td colspan="5"><div>DXd</div></td></tr>
<tr><th>Linker Name</th><td colspan="5"><div>Mc-Gly-Gly-Phe-Gly</div></td></tr>
</tbody></table>
"""


PUBMED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>12345678</PMID>
      <Article>
        <Journal><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue><Title>ADC Journal</Title></Journal>
        <ArticleTitle>HER2 antibody-drug conjugates in breast cancer</ArticleTitle>
        <Abstract><AbstractText Label="BACKGROUND">T-DXd targets HER2.</AbstractText></Abstract>
        <AuthorList><Author><LastName>Wang</LastName><Initials>Y</Initials></Author></AuthorList>
      </Article>
    </MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1/example</ArticleId></ArticleIdList></PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


TRIAL_PAGE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000001",
                    "briefTitle": "A study of T-DXd in HER2-positive cancer",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2025-01"},
                    "lastUpdatePostDateStruct": {"date": "2026-01-01"},
                },
                "designModule": {
                    "phases": ["PHASE2"],
                    "enrollmentInfo": {"count": 50},
                },
                "conditionsModule": {"conditions": ["Breast Cancer"]},
                "armsInterventionsModule": {
                    "interventions": [
                        {
                            "name": "Trastuzumab deruxtecan",
                            "otherNames": ["T-DXd"],
                        }
                    ]
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Example Sponsor"}
                },
                "outcomesModule": {
                    "primaryOutcomes": [{"measure": "Objective response rate"}]
                },
            }
        }
    ]
}


class IngestionTests(unittest.TestCase):
    def test_adcdb_search_parser_returns_named_results(self) -> None:
        content = b"""
        <div><span>ADC ID: DRG000001</span>
        <span><b>ADC Name: </b>Wrong result</span>
        <a href="/data/adc/details/DRG000001">ADC Info</a></div>
        <div><span>ADC ID: DRG000002</span>
        <span><b>ADC Name: </b>Trastuzumab deruxtecan</span>
        <a href="/data/adc/details/DRG000002">ADC Info</a></div>
        """
        results = parse_adcdb_search_results(content)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[1][1], "Trastuzumab deruxtecan")

    def test_adcdb_detail_parser(self) -> None:
        record = parse_adcdb_detail(
            ADCDB_HTML,
            detail_url="https://adcdb.example/DRG0TEST1",
            raw_path="raw/adcdb.html",
            checksum="abc",
        )
        self.assertEqual(record.adcdb_id, "DRG0TEST1")
        self.assertEqual(record.adc_name, "Trastuzumab deruxtecan")
        self.assertEqual(record.dar, 8.0)
        self.assertIn("T-DXd", record.synonyms)

    def test_pubmed_parser_and_normalized_links(self) -> None:
        documents = parse_pubmed_xml(
            PUBMED_XML,
            raw_path="raw/pubmed.xml",
            checksum="abc",
        )
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0].doi, "10.1/example")
        normalizer = EntityNormalizer()
        links, evidence = document_links_and_evidence(documents, normalizer)
        linked_ids = {(link.entity_type, link.entity_id) for link in links}
        self.assertIn(("adc", "adc_001"), linked_ids)
        self.assertIn(("target", "HER2"), linked_ids)
        self.assertGreaterEqual(len(evidence), 2)

    def test_trial_parser_and_links(self) -> None:
        trials = parse_trials_page(TRIAL_PAGE, raw_path="raw/trials.json", checksum="abc")
        self.assertEqual(len(trials), 1)
        self.assertEqual(trials[0].enrollment, 50)
        links, evidence = trial_links_and_evidence(trials, EntityNormalizer())
        self.assertTrue(any(link.entity_id == "adc_001" for link in links))
        self.assertTrue(any(item.value == "RECRUITING" for item in evidence))

    def test_repository_round_trip_and_quality_metrics(self) -> None:
        documents = parse_pubmed_xml(
            PUBMED_XML,
            raw_path="raw/pubmed.xml",
            checksum="abc",
        )
        trials = parse_trials_page(TRIAL_PAGE, raw_path="raw/trials.json", checksum="abc")
        normalizer = EntityNormalizer()
        document_links, document_evidence = document_links_and_evidence(
            documents, normalizer
        )
        trial_links, trial_evidence = trial_links_and_evidence(trials, normalizer)

        with WorkspaceTemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "test.db"
            initialize_database(database_path, DEFAULT_SEED_PATH)
            upsert_documents(database_path, documents)
            upsert_trials(database_path, trials)
            upsert_entity_links(database_path, [*document_links, *trial_links])
            upsert_evidence(database_path, [*document_evidence, *trial_evidence])
            metrics = data_quality_metrics(database_path)

        self.assertEqual(metrics["document_count"], 1)
        self.assertEqual(metrics["trial_count"], 1)
        self.assertEqual(metrics["abstract_coverage"], 1.0)
        self.assertGreater(metrics["evidence_count"], 0)

    def test_normalize_text_is_punctuation_insensitive(self) -> None:
        self.assertEqual(normalize_text("TROP-2"), "trop 2")
        self.assertEqual(normalize_text("TROP 2"), "trop 2")


if __name__ == "__main__":
    unittest.main()
