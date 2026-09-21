# 2026-09-21 public benchmark reproducibility record

This record binds the public development comparison to code commit
`c00b0dbb1b7c1a62803a2cd7b0d0b9b1a03c492c`. It is an engineering diagnostic,
not a hidden-test or publication result. The benchmark remains
`human_review_required=true`.

## Fixed inputs and conditions

The system and offline baseline used the same public database, retrieval index,
98-question development file, and deterministic offline generator. Both runs
recorded:

| Item | Value |
| --- | --- |
| Database data version | `data_465aab2dc23d8b11c769c7a8b61c6f3144f496ca02355e0318321f2b6ebc93d4` |
| Retrieval corpus | `corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca` |
| Question count | 98 |
| Question-set object hash | `sha256:b22f528867cf6197df1b48f2e328e812abcc16e8f03f480e13fb04cb357aeec0` |
| Prompt version | `public-benchmark-v1` |
| Generator | `extractive-offline-v1` |
| Network | disabled |
| Retrieval | sparse, top-k 5, candidate limit 60 |
| Scoring | automatic diagnostics only |

The runs were reproduced with:

```powershell
$env:PYTHONPATH="src"
python scripts/run_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --output .test_tmp/public_benchmark_system-c00b0db.json

python scripts/run_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --disable-structured-routing `
  --output .test_tmp/public_benchmark_baseline-c00b0db.json

python scripts/compare_public_benchmark.py `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --system-report .test_tmp/public_benchmark_system-c00b0db.json `
  --baseline-report .test_tmp/public_benchmark_baseline-c00b0db.json `
  --output .test_tmp/public_benchmark_comparison-c00b0db.json
```

The first attempted command included `--seed 0`; that option is a seed CSV
path, so the run failed closed with `FileNotFoundError: ... '0'`. The corrected
commands above omit that option and completed successfully.

## Automatic paired diagnostics

| Metric | System | Offline baseline | Difference | 95% bootstrap CI |
| --- | ---: | ---: | ---: | ---: |
| Route match | 1.0000 | 0.3061 | 0.6939 | [0.6020, 0.7755] |
| Status coverage | 1.0000 | 0.9796 | 0.0204 | [0.0000, 0.0510] |
| Answer field/exact match | 0.9694 | 0.2551 | 0.7143 | [0.6327, 0.7959] |
| Evidence recall | 0.9694 | 0.3980 | 0.5714 | [0.4796, 0.6735] |
| Refusal correctness | 1.0000 | 0.9796 | 0.0204 | [0.0000, 0.0510] |

The comparison uses paired bootstrap with 2,000 iterations and exact McNemar
tests. Its labels are automatic expected-field/status outcomes defined by the
public benchmark, not human semantic judgments. They must not be reported as
clinical accuracy, expert gold labels, or generalization to an unseen set.

## Component ablation

The exact-identifier-routing ablation was run on the same database, question
set, generator, and retrieval conditions:

```powershell
$env:PYTHONPATH="src"
python scripts/run_identifier_routing_ablation.py `
  --database data/processed/adc_public_2026-09-30.db `
  --questions data/annotations/public_benchmark_v1.jsonl `
  --window-id public-benchmark-v1-2026-09-21-c00b0db `
  --output .test_tmp/identifier_routing_ablation-c00b0db.json
```

It evaluated 98 questions, changed no question IDs, and preserved all paired
route and status outcomes. This is a component-level engineering observation;
it does not establish semantic correctness without independent human review.

## Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| system report | `cbca5d2899cd65f0e063f7eaf8929c92e0526604ab337ec7c5f1c9dfb8e7b471` |
| baseline report | `bd337c91d9c91684629b820bc4d4f9c6e3d113c39521c17519eba34d76091b57` |
| paired comparison | `f5311d129374c32c6b3b676b54f01bb903df300e8a019e228012634af8a791b6` |
| identifier-routing ablation | `c6a6a410d1ea3a8241e30b80af8ca68914acddc686ec024741bbb65b636b194d` |

All four files remain local ignored artifacts. The public repository contains
the commands, schemas, and this provenance record, but no generated database,
index, raw response, reviewer identity, or human label export.
