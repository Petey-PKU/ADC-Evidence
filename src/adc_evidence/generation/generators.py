from __future__ import annotations

import os
import re
from typing import Protocol

from adc_evidence.config import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_SILICONFLOW_BASE_URL,
    DEFAULT_SILICONFLOW_MODEL,
    load_local_environment,
)
from adc_evidence.generation.citations import NumberedSource
from adc_evidence.generation.models import GeneratorResponse
from adc_evidence.generation.prompts import GENERATION_INSTRUCTIONS, build_generation_input
from adc_evidence.rag.query_expansion import expand_query


class AnswerGenerator(Protocol):
    backend_name: str
    model_name: str

    def generate(
        self, question: str, sources: list[NumberedSource]
    ) -> GeneratorResponse: ...


class OpenAIResponsesGenerator:
    backend_name = "openai"

    def __init__(self, model_name: str | None = None, api_key: str | None = None) -> None:
        load_local_environment()
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "OpenAI generation requires: python -m pip install -e '.[generation]'"
            ) from exc

        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if not resolved_key:
            raise RuntimeError("OPENAI_API_KEY is not configured.")
        self.model_name = (
            model_name
            or os.getenv("OPENAI_MODEL")
            or os.getenv("ADC_LLM_MODEL")
            or DEFAULT_OPENAI_MODEL
        )
        self._client = OpenAI(api_key=resolved_key)

    def generate(
        self, question: str, sources: list[NumberedSource]
    ) -> GeneratorResponse:
        response = self._client.responses.create(
            model=self.model_name,
            reasoning={"effort": "low"},
            instructions=GENERATION_INSTRUCTIONS,
            input=build_generation_input(question, sources),
            max_output_tokens=700,
            store=False,
        )
        usage_object = getattr(response, "usage", None)
        usage = {
            name: int(value)
            for name in ("input_tokens", "output_tokens", "total_tokens")
            if (value := getattr(usage_object, name, None)) is not None
        }
        return GeneratorResponse(
            text=response.output_text.strip(),
            backend=self.backend_name,
            model=str(getattr(response, "model", None) or self.model_name),
            usage=usage,
            response_id=getattr(response, "id", None),
        )


class SiliconFlowChatGenerator:
    """SiliconFlow adapter using its OpenAI-compatible Chat Completions API."""

    backend_name = "siliconflow"

    def __init__(
        self,
        model_name: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        load_local_environment()
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "SiliconFlow generation requires: "
                "python -m pip install -e '.[generation]'"
            ) from exc

        resolved_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        if not resolved_key:
            raise RuntimeError("SILICONFLOW_API_KEY is not configured.")
        self.model_name = (
            model_name
            or os.getenv("SILICONFLOW_MODEL")
            or os.getenv("ADC_LLM_MODEL")
            or DEFAULT_SILICONFLOW_MODEL
        )
        self.base_url = (
            base_url
            or os.getenv("SILICONFLOW_BASE_URL")
            or DEFAULT_SILICONFLOW_BASE_URL
        ).rstrip("/")
        self._client = OpenAI(api_key=resolved_key, base_url=self.base_url)

    def generate(
        self, question: str, sources: list[NumberedSource]
    ) -> GeneratorResponse:
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": GENERATION_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": build_generation_input(question, sources),
                },
            ],
            temperature=0.0,
            max_tokens=700,
            stream=False,
        )
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("SiliconFlow returned an empty answer.")

        usage_object = getattr(response, "usage", None)
        usage_names = {
            "input_tokens": "prompt_tokens",
            "output_tokens": "completion_tokens",
            "total_tokens": "total_tokens",
        }
        usage = {
            target_name: int(value)
            for target_name, source_name in usage_names.items()
            if (value := getattr(usage_object, source_name, None)) is not None
        }
        return GeneratorResponse(
            text=content.strip(),
            backend=self.backend_name,
            model=str(getattr(response, "model", None) or self.model_name),
            usage=usage,
            response_id=getattr(response, "id", None),
        )


class ExtractiveGenerator:
    """Deterministic offline baseline for pipeline tests and demos."""

    backend_name = "extractive"
    model_name = "deterministic-extractive-v1"

    @staticmethod
    def _query_terms(question: str) -> set[str]:
        expanded = expand_query(question).casefold()
        terms = set(re.findall(r"[a-z0-9]+", expanded))
        concept_map = {
            "靶点": {"target", "antigen"},
            "载荷": {"payload", "warhead"},
            "连接子": {"linker"},
            "药物抗体比": {"dar"},
            "dar": {"dar"},
            "研发状态": {"development", "status"},
            "阶段": {"phase"},
            "状态": {"status"},
            "主要终点": {"primary", "outcomes", "endpoint"},
            "安全性": {"safety", "toxicity"},
            "疗效": {"efficacy", "response", "survival"},
            "机制": {"mechanism", "internalized", "release", "activity"},
            "细胞内转运": {"internalized", "trafficking", "lysosome"},
            "内化": {"internalized", "internalization"},
            "释放": {"release", "released"},
            "临床前": {"preclinical"},
            "抗肿瘤": {"antitumor", "activity"},
        }
        lowered = question.casefold()
        for marker, additions in concept_map.items():
            if marker in lowered:
                terms.update(additions)
        return {term for term in terms if len(term) > 1}

    def generate(
        self, question: str, sources: list[NumberedSource]
    ) -> GeneratorResponse:
        terms = self._query_terms(question)
        lowered_question = question.casefold()
        selected: list[tuple[str, str]] = []

        def add(unit: str, citation_id: str) -> None:
            normalized = " ".join(unit.casefold().split())
            if unit.strip() and normalized not in {" ".join(item[0].casefold().split()) for item in selected}:
                selected.append((unit.strip()[:420].rstrip(), citation_id))

        if sources:
            primary = sources[0]
            lines = [line.strip() for line in primary.excerpt.splitlines() if line.strip()]
            if primary.result.source_type == "adc_profile":
                requested_prefixes: list[str] = []
                field_markers = (
                    (("靶点", "target"), "靶点 / target:"),
                    (("载荷", "payload"), "载荷 / payload:"),
                    (("payload class", "载荷类型"), "载荷类型 / payload class:"),
                    (("dar", "药物抗体比"), "药物抗体比 / DAR:"),
                    (("linker", "连接子"), "连接子 / linker:"),
                    (("linker 类型", "连接子类型"), "连接子类型 / linker type:"),
                    (("研发状态", "development status"), "研发状态 / development status:"),
                    (("企业", "公司", "company"), "企业 / company:"),
                )
                for markers, prefix in field_markers:
                    if any(marker in lowered_question for marker in markers):
                        requested_prefixes.append(prefix.casefold())
                for line in lines:
                    if any(line.casefold().startswith(prefix) for prefix in requested_prefixes):
                        add(line, primary.citation_id)
            elif primary.result.source_type == "clinical_trial":
                wanted_prefixes = ["clinical trial:", "brief title:"]
                if any(marker in lowered_question for marker in ("状态", "招募", "撤回")):
                    wanted_prefixes.append("recruitment status:")
                if any(marker in lowered_question for marker in ("期", "phase", "阶段")):
                    wanted_prefixes.append("phase:")
                if any(marker in lowered_question for marker in ("终点", "outcome", "endpoint")):
                    wanted_prefixes.append("primary outcomes:")
                for line in lines:
                    if any(line.casefold().startswith(prefix) for prefix in wanted_prefixes):
                        add(line, primary.citation_id)
            elif primary.result.source_type == "pubmed":
                add(
                    f"文档 {primary.result.retrieval_document_id}：{primary.result.title}",
                    primary.citation_id,
                )

        candidates: list[tuple[int, int, int, str, str]] = []
        for source_index, source in enumerate(sources):
            units = [
                unit.strip()
                for unit in re.split(r"\n+|(?<=[.!?。！？])\s+", source.excerpt)
                if unit.strip()
            ]
            for unit_index, unit in enumerate(units):
                lowered = unit.casefold()
                score = sum(term in lowered for term in terms)
                if score:
                    candidates.append((score, -source_index, -unit_index, unit, source.citation_id))
        if not candidates and not selected:
            return GeneratorResponse(
                text="REFUSE: 检索片段中没有与问题直接对应的事实。",
                backend=self.backend_name,
                model=self.model_name,
            )

        candidates.sort(reverse=True)
        seen = {" ".join(unit.casefold().split()) for unit, _ in selected}
        for _, _, _, unit, citation_id in candidates:
            if len(selected) >= 4:
                break
            normalized = " ".join(unit.casefold().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            selected.append((unit[:420].rstrip(), citation_id))
        text = "\n".join(
            f"- 证据摘录：{unit} [{citation_id}]" for unit, citation_id in selected
        )
        return GeneratorResponse(
            text=text,
            backend=self.backend_name,
            model=self.model_name,
        )


def openai_configured() -> bool:
    load_local_environment()
    return bool(os.getenv("OPENAI_API_KEY"))


def siliconflow_configured() -> bool:
    load_local_environment()
    return bool(os.getenv("SILICONFLOW_API_KEY"))


def configured_generation_backends() -> list[str]:
    backends = ["extractive"]
    if siliconflow_configured():
        backends.append("siliconflow")
    if openai_configured():
        backends.append("openai")
    return backends


def create_generator(name: str = "auto") -> AnswerGenerator:
    load_local_environment()
    resolved = name.strip().lower()
    if resolved == "auto":
        preferred = os.getenv("ADC_LLM_BACKEND", "").strip().lower()
        if preferred:
            resolved = preferred
        elif openai_configured():
            resolved = "openai"
        elif siliconflow_configured():
            resolved = "siliconflow"
        else:
            resolved = "extractive"
    if resolved == "extractive":
        return ExtractiveGenerator()
    if resolved == "openai":
        return OpenAIResponsesGenerator()
    if resolved == "siliconflow":
        return SiliconFlowChatGenerator()
    raise ValueError(f"Unknown generation backend: {name}")
