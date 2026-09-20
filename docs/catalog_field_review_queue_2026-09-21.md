# Public ADC catalog field-review queue (2026-09-21)

The public catalog contains 23 ADC rows and 299 review items across the
13 fields defined by `build_catalog_field_review_packet.py`. The review packet
is a work queue, not a set of verified facts: all 299 items remain
`pending_primary_check`, and no item has a human verdict or confirmed value.

Rebuild and validate the queue with:

```powershell
$env:PYTHONPATH="src"
python scripts/build_catalog_field_review_packet.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --output artifacts/evaluation/catalog_field_review.current.jsonl `
  --manifest artifacts/evaluation/catalog_field_review.current.manifest.json
python scripts/validate_catalog_field_review.py `
  --packet artifacts/evaluation/catalog_field_review.current.jsonl `
  --manifest artifacts/evaluation/catalog_field_review.current.manifest.json `
  --catalog data/public/marketed_adc_catalog.csv
```

The current packet contains 176 candidate source locators covering 173 unique
ADC-field pairs. They are hints for
human checking and are not accepted as field-level evidence until a reviewer
records a source locator, a controlled verdict, and an independent human
review origin. The packet SHA-256 is
`a24852d2e858c25537e018c37e64f45a3b27e6f8278d4141ba9a2fc0bfddbd34`; its
manifest SHA-256 is
`3164a96e9d9dab43700dfd60167bf475fec06587ac943738dc8eec2129f99442`.

Until the required independent primary and secondary reviews are supplied,
the catalog source-quality gate remains `needs_review` and the project must
not describe these rows as expert-verified or publication-grade gold data.

The scope validator records 21 core ADC rows and two excluded modality rows
(`adc_021` photoimmunoconjugate and `adc_023` recombinant immunotoxin). The
catalog status distribution is 21 core marketed, one extended marketed, and
one extended withdrawn record. These are explicit catalog-scope labels; they
do not independently establish regulatory status.

The source-content triage was rerun on 2026-09-21 against all 23 candidate
URLs. The updated report SHA-256 is
`051bf998399888ff29b91331de30686a2c2054a69f7ecfe4eff8e1799c0f9ab4`.
For the eight core fact fields, candidate locator coverage is:

| Field | Locator pairs | Missing pairs |
|---|---:|---:|
| target | 23 / 23 | 0 |
| antibody | 23 / 23 | 0 |
| linker_name | 22 / 23 | 1 |
| linker_type | 22 / 23 | 1 |
| payload_name | 23 / 23 | 0 |
| payload_class | 23 / 23 | 0 |
| dar | 22 / 23 | 1 |
| indication | 15 / 23 | 8 |

The automatic value pre-screen found 22 matches among 134 eligible candidate
values (`0.1642`). This is a triage signal only: PDFs and page structure can
hide values, terminology can differ, and no match is treated as a verified
claim. All candidate locators and values remain pending independent human
source review.
