from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from adc_evidence.config import (
    DEFAULT_SILICONFLOW_BASE_URL,
    DEFAULT_SILICONFLOW_MODEL,
    DEFAULT_TAVILY_BASE_URL,
    load_local_environment,
)
from adc_evidence.evaluation.benchmark import build_external_arm_report


DIRECT_SYSTEM_PROMPT = """你是三组对照评测中的通用大模型直接回答组。
只使用模型自身已有知识回答，不得联网，不得声称访问了外部来源。
不知道或问题要求个体化医疗、治疗或投资决策时应明确拒答。
输出严格 JSON：{"status":"answered 或 refused","answer":"中文回答"}。"""

WEB_SYSTEM_PROMPT = """你是三组对照评测中的通用大模型联网回答组。
使用用户消息中提供的实时网页搜索结果回答；事实后用 [S1] 格式标出直接来源。
搜索结果不足时明确说明，不得编造来源。个体化医疗、治疗或投资决策应明确拒答。
输出严格 JSON：{"status":"answered 或 refused","answer":"中文回答"}。"""


class SearchClient(Protocol):
    provider_name: str

    def search(self, query: str) -> dict[str, object]: ...


class BenchmarkModelClient(Protocol):
    model_name: str

    def answer(
        self,
        question: str,
        *,
        sources: list[dict[str, object]] | None = None,
        accessed_at: str | None = None,
    ) -> dict[str, object]: ...


class TavilySearchClient:
    provider_name = "tavily-search-basic-v1"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        max_results: int = 5,
        timeout_seconds: int = 30,
    ) -> None:
        load_local_environment()
        self._api_key = api_key or os.getenv("TAVILY_API_KEY")
        if not self._api_key:
            raise RuntimeError("TAVILY_API_KEY is not configured.")
        self.base_url = (
            base_url or os.getenv("TAVILY_BASE_URL") or DEFAULT_TAVILY_BASE_URL
        ).rstrip("/")
        self.max_results = max(1, min(max_results, 10))
        self.timeout_seconds = timeout_seconds

    def search(self, query: str) -> dict[str, object]:
        payload = json.dumps(
            {
                "query": query,
                "search_depth": "basic",
                "topic": "general",
                "max_results": self.max_results,
                "include_answer": False,
                "include_raw_content": False,
                "include_images": False,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/search",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "ADC-Evidence-v0.6-benchmark",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"Tavily search returned HTTP {exc.code}.") from exc
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError("Tavily search request failed.") from exc
        results = []
        for row in body.get("results", []):
            url = str(row.get("url", "")).strip()
            if not url:
                continue
            results.append(
                {
                    "title": str(row.get("title", "")).strip() or url,
                    "url": url,
                    "content": str(row.get("content", "")).strip()[:1800],
                    "score": row.get("score"),
                }
            )
        usage = body.get("usage")
        reported_credits = (
            usage.get("credits")
            if isinstance(usage, dict)
            else usage if isinstance(usage, (int, float)) else None
        )
        return {
            "results": results,
            "request_id": body.get("request_id"),
            "response_time": body.get("response_time"),
            "credits": reported_credits,
            # Tavily documents basic search as one credit per request. Keep the
            # estimate distinct because some successful responses omit usage.
            "estimated_credits": 1,
        }


class SiliconFlowBenchmarkClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
    ) -> None:
        load_local_environment()
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "SiliconFlow benchmark requires: "
                "python -m pip install -e '.[generation]'"
            ) from exc
        resolved_key = api_key or os.getenv("SILICONFLOW_API_KEY")
        if not resolved_key:
            raise RuntimeError("SILICONFLOW_API_KEY is not configured.")
        self.model_name = (
            model_name
            or os.getenv("SILICONFLOW_BENCHMARK_MODEL")
            or os.getenv("SILICONFLOW_MODEL")
            or DEFAULT_SILICONFLOW_MODEL
        )
        resolved_base_url = (
            base_url
            or os.getenv("SILICONFLOW_BASE_URL")
            or DEFAULT_SILICONFLOW_BASE_URL
        ).rstrip("/")
        self._client = OpenAI(api_key=resolved_key, base_url=resolved_base_url)

    def answer(
        self,
        question: str,
        *,
        sources: list[dict[str, object]] | None = None,
        accessed_at: str | None = None,
    ) -> dict[str, object]:
        if sources is None:
            system_prompt = DIRECT_SYSTEM_PROMPT
            user_prompt = question
        else:
            system_prompt = WEB_SYSTEM_PROMPT
            source_text = "\n\n".join(
                f"[S{index}] {row['title']}\nURL: {row['url']}\n{row['content']}"
                for index, row in enumerate(sources, start=1)
            )
            user_prompt = (
                f"访问时间：{accessed_at}\n问题：{question}\n\n"
                f"网页搜索结果：\n{source_text or '（没有检索到结果）'}"
            )
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1000,
            stream=False,
        )
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("SiliconFlow returned an empty benchmark answer.")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SiliconFlow benchmark answer was not valid JSON.") from exc
        status = str(parsed.get("status", ""))
        answer = str(parsed.get("answer", "")).strip()
        if status not in {"answered", "refused"} or not answer:
            raise RuntimeError("SiliconFlow benchmark answer failed schema validation.")
        usage_object = getattr(response, "usage", None)
        usage = {
            target: int(value)
            for target, source in {
                "input_tokens": "prompt_tokens",
                "output_tokens": "completion_tokens",
                "total_tokens": "total_tokens",
            }.items()
            if (value := getattr(usage_object, source, None)) is not None
        }
        return {
            "status": status,
            "answer": answer,
            "usage": usage,
            "response_id": getattr(response, "id", None),
            "model": str(getattr(response, "model", None) or self.model_name),
        }


def _web_citations(
    answer: str,
    sources: list[dict[str, object]],
) -> list[dict[str, object]]:
    cited_numbers = {
        int(value) for value in re.findall(r"\[S(\d+)\]", answer)
    }
    citations = []
    for index, source in enumerate(sources, start=1):
        if index not in cited_numbers:
            continue
        url = str(source["url"])
        url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
        citations.append(
            {
                "citation_id": f"S{index}",
                "chunk_id": f"web:{url_hash}:0",
                "retrieval_document_id": f"web:{url_hash}",
                "source_type": "web",
                "title": str(source["title"]),
                "source_url": url,
                "excerpt": str(source.get("content", ""))[:1200],
            }
        )
    return citations


def run_siliconflow_external_arm(
    arm: str,
    *,
    questions: list[dict[str, object]],
    evaluation_window_id: str,
    model_client: BenchmarkModelClient | None = None,
    search_client: SearchClient | None = None,
    evaluated_at: str | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    if arm not in {"direct_model", "web_model"}:
        raise ValueError("External arm must be direct_model or web_model")
    model_client = model_client or SiliconFlowBenchmarkClient()
    if arm == "web_model":
        search_client = search_client or TavilySearchClient()
    rows = []
    total_usage: dict[str, int] = {}
    for question in questions:
        question_text = str(question["question"])
        accessed_at = datetime.now(UTC).isoformat()
        try:
            search_payload: dict[str, object] = {"results": []}
            sources: list[dict[str, object]] | None = None
            if arm == "web_model" and search_client is not None:
                search_payload = search_client.search(question_text)
                sources = list(search_payload.get("results", []))
            generated = model_client.answer(
                question_text,
                sources=sources,
                accessed_at=accessed_at if sources is not None else None,
            )
            usage = dict(generated.get("usage", {}))
            for key, value in usage.items():
                total_usage[key] = total_usage.get(key, 0) + int(value)
            answer = str(generated["answer"])
            rows.append(
                {
                    "question_id": question["question_id"],
                    "status": generated["status"],
                    "answer": answer,
                    "citations": (
                        _web_citations(answer, sources or [])
                        if arm == "web_model"
                        else []
                    ),
                    "accessed_at": accessed_at if arm == "web_model" else None,
                    "search_provider": (
                        search_client.provider_name
                        if arm == "web_model" and search_client is not None
                        else None
                    ),
                    "search_result_count": len(sources or []),
                    "search_request_id": search_payload.get("request_id"),
                    "search_credits": search_payload.get("credits"),
                    "search_credit_estimate": search_payload.get(
                        "estimated_credits"
                    ),
                    "usage": usage,
                    "response_id": generated.get("response_id"),
                    "model": generated.get("model", model_client.model_name),
                }
            )
        except Exception as exc:  # noqa: BLE001 - errors belong in the report
            rows.append(
                {
                    "question_id": question["question_id"],
                    "status": "error",
                    "answer": "该评测调用失败，未产生可审核回答。",
                    "citations": [],
                    "error_type": type(exc).__name__,
                }
            )
    report = build_external_arm_report(
        arm,
        rows,
        model=model_client.model_name,
        evaluated_at=evaluated_at or datetime.now(UTC).isoformat(),
        evaluation_window_id=evaluation_window_id,
        questions=questions,
        run_id=run_id,
    )
    report["usage"] = total_usage
    report["search_provider"] = (
        search_client.provider_name
        if arm == "web_model" and search_client is not None
        else None
    )
    return report
