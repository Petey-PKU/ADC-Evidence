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

The current packet contains 187 candidate source locators covering 184 unique
ADC-field pairs. They are hints for
human checking and are not accepted as field-level evidence until a reviewer
records a source locator, a controlled verdict, and an independent human
review origin. The packet SHA-256 is
`dd8deec4b9498e9bc6fcd68cc7c9160243ef95747d367c4a19777ea87a003a7f`; its
manifest SHA-256 is
`24e656f1fe9a7ee3f2e259e98bb5bbe5d0a08cf70bf13ec4d8ebb078a9087145`.

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
`8e941f470e41993d0e7d5e1a279d4e24a1668d368c20b8497af5b6ca0c125062`.
For the eight core fact fields, candidate locator coverage is:

| Field | Locator pairs | Missing pairs |
|---|---:|---:|
| target | 23 / 23 | 0 |
| antibody | 23 / 23 | 0 |
| linker_name | 23 / 23 | 0 |
| linker_type | 23 / 23 | 0 |
| payload_name | 23 / 23 | 0 |
| payload_class | 23 / 23 | 0 |
| dar | 23 / 23 | 0 |
| indication | 23 / 23 | 0 |

The automatic value pre-screen found 23 matches among 137 eligible candidate
values (`0.1679`; indication values matched 7/17 eligible source texts). This is a triage signal only: PDFs and page structure can
hide values, terminology can differ, and no match is treated as a verified
claim. All candidate locators and values remain pending independent human
source review.
