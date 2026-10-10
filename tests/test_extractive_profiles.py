from __future__ import annotations

import unittest

from adc_evidence.generation.citations import number_sources
from adc_evidence.generation.generators import ExtractiveGenerator
from adc_evidence.rag.retriever import SearchResult


def profile_result(adc_id: str, name: str, lines: str, rank: int = 1) -> SearchResult:
    return SearchResult(
        rank=rank,
        chunk_id=f"adc_profile:{adc_id}#chunk-000",
        retrieval_document_id=f"adc_profile:{adc_id}",
        source_type="adc_profile",
        source_record_id=adc_id,
        title=f"ADC profile: {name}",
        content=lines,
        source_url=f"https://example.test/{adc_id}",
        score=10.0 - rank,
        metadata={"adc_ids": [adc_id]},
    )


class ExtractiveProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = ExtractiveGenerator()

    def test_profile_field_request_does_not_mix_other_adc(self) -> None:
        sources = number_sources([
            profile_result(
                "alpha",
                "Alpha ADC",
                "ADC name: Alpha ADC\n连接子 / linker: Val-Cit\n连接子类型 / linker type: cleavable\n药物抗体比 / DAR: 4.0",
            ),
            profile_result(
                "beta",
                "Beta ADC",
                "ADC name: Beta ADC\n连接子 / linker: MC\n连接子类型 / linker type: non-cleavable\n药物抗体比 / DAR: 3.5",
                rank=2,
            ),
        ])
        response = self.generator.generate("Alpha ADC 的 linker type 是什么？", sources)

        self.assertIn("连接子类型 / linker type: cleavable", response.text)
        self.assertNotIn("non-cleavable", response.text)
        self.assertNotIn("DAR", response.text)

    def test_profile_linker_name_request_does_not_return_linker_type(self) -> None:
        sources = number_sources([
            profile_result(
                "alpha",
                "Alpha ADC",
                "ADC name: Alpha ADC\n连接子 / linker: Val-Cit\n连接子类型 / linker type: cleavable",
            ),
        ])
        response = self.generator.generate("Alpha ADC 的 linker name 是什么？", sources)

        self.assertIn("连接子 / linker: Val-Cit", response.text)
        self.assertNotIn("连接子类型 / linker type:", response.text)


if __name__ == "__main__":
    unittest.main()
