from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_POLICY_PATH = PROJECT_ROOT / "configs" / "evidence_policy.json"
DEFAULT_SEED_PATH = Path(
    os.getenv("ADC_SEED_PATH", str(PROJECT_ROOT / "data" / "sample" / "adcs.csv"))
)
DEFAULT_DATABASE_PATH = Path(
    os.getenv(
        "ADC_DATABASE_PATH",
        str(PROJECT_ROOT / "data" / "processed" / "adc_evidence.db"),
    )
)
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed"
QUALITY_REPORT_PATH = PROCESSED_DATA_PATH / "data_quality_report.json"
ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "annotations"
RETRIEVAL_QUESTIONS_PATH = ANNOTATIONS_PATH / "retrieval_questions.jsonl"
GENERATION_QUESTIONS_PATH = ANNOTATIONS_PATH / "generation_questions.jsonl"
FROZEN_BENCHMARK_QUESTIONS_PATH = (
    ANNOTATIONS_PATH / "v0.6_frozen_test_questions.jsonl"
)
VECTOR_INDEX_PATH = Path(
    os.getenv("ADC_VECTOR_INDEX_PATH", str(PROJECT_ROOT / "artifacts" / "vector_index"))
)
EVALUATION_PATH = PROJECT_ROOT / "artifacts" / "evaluation"
GENERATION_REPORT_PATH = EVALUATION_PATH / "generation_report.json"
RETRIEVAL_REPORT_PATH = EVALUATION_PATH / "retrieval_report.json"
BAD_CASE_REPORT_PATH = EVALUATION_PATH / "bad_case_report.json"
BAD_CASE_MARKDOWN_PATH = PROJECT_ROOT / "docs" / "bad_case_report.md"
BENCHMARK_EVALUATION_PATH = EVALUATION_PATH / "v0.6_benchmark"
BENCHMARK_REPORT_PATH = BENCHMARK_EVALUATION_PATH / "comparison_report.json"
BENCHMARK_REVIEW_PACKET_PATH = BENCHMARK_EVALUATION_PATH / "blind_review_packet.json"
BENCHMARK_IDENTITY_MAP_PATH = BENCHMARK_EVALUATION_PATH / "blind_identity_map.json"
BENCHMARK_SUMMARY_PATH = BENCHMARK_EVALUATION_PATH / "human_summary.json"
BENCHMARK_BAD_CASE_PATH = BENCHMARK_EVALUATION_PATH / "human_bad_cases.json"
BENCHMARK_REGRESSION_CANDIDATES_PATH = (
    BENCHMARK_EVALUATION_PATH / "regression_candidates.jsonl"
)
BENCHMARK_REGRESSION_PATH = ANNOTATIONS_PATH / "v0.6_regression_questions.jsonl"
REVIEW_EXPORT_JSONL_PATH = EVALUATION_PATH / "expert_reviews.jsonl"
REVIEW_EXPORT_CSV_PATH = EVALUATION_PATH / "expert_reviews.csv"
REVIEW_EXPORT_MANIFEST_PATH = EVALUATION_PATH / "expert_reviews_manifest.json"
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"
DEFAULT_TAVILY_BASE_URL = "https://api.tavily.com"

# Backward-compatible alias for code or local configuration created before the
# generation backends received provider-specific model settings.
DEFAULT_LLM_MODEL = DEFAULT_OPENAI_MODEL


def environment_flag(name: str, *, default: bool = False) -> bool:
    """Read a strict boolean environment flag.

    Accepted true values are ``1``, ``true``, ``yes`` and ``on``; accepted
    false values are ``0``, ``false``, ``no`` and ``off``. Invalid values fail
    fast so a misspelled production guard cannot silently disable itself.
    """
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of: 1, true, yes, on, 0, false, no, off"
    )


def load_local_environment() -> None:
    """Load secrets from an explicitly selected local file without overriding env.

    ``ADC_ENV_FILE`` is intentionally an operating-system environment variable,
    not a value discovered by searching parent or sibling directories. This keeps
    the public repository independent from any particular private workspace.
    """
    configured_path = os.getenv("ADC_ENV_FILE", "").strip()
    env_path = (
        Path(configured_path).expanduser()
        if configured_path
        else PROJECT_ROOT / ".env"
    )
    if configured_path and not env_path.is_file():
        raise RuntimeError("ADC_ENV_FILE does not point to a readable file.")
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "Loading a local env file requires: "
            "python -m pip install -e '.[generation]'"
        ) from exc
    load_dotenv(env_path, override=False)
