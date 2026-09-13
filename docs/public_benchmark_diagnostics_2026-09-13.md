# Public benchmark v1: reproducible offline diagnostics

This record describes one deterministic run on 2026-09-13. It is an engineering
diagnostic and is not a human correctness study or a submission result.

## Frozen inputs

- Questions: 98 rows (`dev=54`, `public_smoke=44`)
- Question file SHA-256: `sha256:88e2cf7d74a0c6ec0e3cf8b83151e970a8c044ce7e722f90b72736feeb998605`
- Question-set SHA-256: `sha256:b3877f9f56a1699466b5ede76dbf7f4d644fb500a8a4e1c156cec6770901b18d`
- Database data version: `data_cf0c057134e4440eff28353b5a1e6989d8a5c7a90e3af44b5978f1506cbf0cbe`
- Retrieval corpus: `corpus_c0c5d4adf458371bddf8cc75ac62c2f58fae5fa73da7e1b8c1b66f7646f5f16c`
- Network access: disabled; generator: `extractive-offline-v1`
- Arms: ADC-Evidence structured routing and an offline RAG baseline using the same database, index, questions, and retrieval budget

## Automatic paired diagnostics

| Metric | ADC-Evidence | Offline RAG baseline | Difference | 95% bootstrap CI | Exact McNemar p |
|---|---:|---:|---:|---:|---:|
| Route match | 1.0000 | 0.3061 | 0.6939 | [0.6020, 0.7755] | <0.001 |
| Expected status coverage | 1.0000 | 0.9796 | 0.0204 | [0.0000, 0.0510] | 0.500 |
| Answer field score | 0.9694 | 0.2653 | 0.7041 | [0.6224, 0.7959] | <0.001 |
| Evidence-source recall | 0.9694 | 0.4082 | 0.5612 | [0.4694, 0.6633] | <0.001 |
| Refusal correctness | 1.0000 | 0.9796 | 0.0204 | [0.0000, 0.0510] | 0.500 |

The answer field score and evidence recall are computed from serialized claims
and source IDs, so they do not judge whether a medical expert considers the
answer clinically sufficient. The paired tests treat the two automatic outputs
as binary diagnostic signals; they do not convert them into semantic labels.

## Reproduction

```powershell
$env:PYTHONPATH = "src"
$env:ADC_OFFLINE_ONLY = "true"
.venv/Scripts/python.exe scripts/run_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --output artifacts/evaluation/public_benchmark_v1_report.json

.venv/Scripts/python.exe scripts/run_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --disable-structured-routing `
  --output artifacts/evaluation/public_benchmark_v1_baseline_report.json

.venv/Scripts/python.exe scripts/compare_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --system-report artifacts/evaluation/public_benchmark_v1_report.json `
  --baseline-report artifacts/evaluation/public_benchmark_v1_baseline_report.json `
  --output artifacts/evaluation/public_benchmark_v1_comparison.json
```

Before a paper uses these numbers, the benchmark must be replaced or extended
with a separately frozen access-controlled set. At least two independent human
reviewers must score answer correctness, evidence support, citation validity,
completeness, and refusal appropriateness, with adjudication and a predeclared
statistical analysis.
