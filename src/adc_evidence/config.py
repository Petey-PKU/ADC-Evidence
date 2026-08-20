from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEED_PATH = PROJECT_ROOT / "data" / "sample" / "adcs.csv"
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "adc_evidence.db"
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw"
PROCESSED_DATA_PATH = PROJECT_ROOT / "data" / "processed"
QUALITY_REPORT_PATH = PROCESSED_DATA_PATH / "data_quality_report.json"
ANNOTATIONS_PATH = PROJECT_ROOT / "data" / "annotations"
RETRIEVAL_QUESTIONS_PATH = ANNOTATIONS_PATH / "retrieval_questions.jsonl"
GENERATION_QUESTIONS_PATH = ANNOTATIONS_PATH / "generation_questions.jsonl"
VECTOR_INDEX_PATH = PROJECT_ROOT / "artifacts" / "vector_index"
EVALUATION_PATH = PROJECT_ROOT / "artifacts" / "evaluation"
GENERATION_REPORT_PATH = EVALUATION_PATH / "generation_report.json"
RETRIEVAL_REPORT_PATH = EVALUATION_PATH / "retrieval_report.json"
BAD_CASE_REPORT_PATH = EVALUATION_PATH / "bad_case_report.json"
BAD_CASE_MARKDOWN_PATH = PROJECT_ROOT / "docs" / "bad_case_report.md"
REVIEW_EXPORT_JSONL_PATH = EVALUATION_PATH / "expert_reviews.jsonl"
REVIEW_EXPORT_CSV_PATH = EVALUATION_PATH / "expert_reviews.csv"
REVIEW_EXPORT_MANIFEST_PATH = EVALUATION_PATH / "expert_reviews_manifest.json"
DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
DEFAULT_OPENAI_MODEL = "gpt-5-mini"
DEFAULT_SILICONFLOW_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
DEFAULT_SILICONFLOW_BASE_URL = "https://api.siliconflow.cn/v1"

# Backward-compatible alias for code or local configuration created before the
# generation backends received provider-specific model settings.
DEFAULT_LLM_MODEL = DEFAULT_OPENAI_MODEL
