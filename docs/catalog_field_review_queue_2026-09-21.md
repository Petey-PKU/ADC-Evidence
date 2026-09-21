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

The current packet contains 235 candidate source locators covering 232 unique
ADC-field pairs. They are hints for
human checking and are not accepted as field-level evidence until a reviewer
records a source locator, a controlled verdict, and an independent human
review origin. The packet SHA-256 is
`47d44ee97238c79bec41dc2401d08ca3f8b9de44f87ebce3bad7ab29bb222663`; its
manifest SHA-256 is
`d08132a72301c5fb0feeef18e91eede3011f5c837f9c545c850dda778346b57e`.

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
`d2c786e5297efa97fac5f14f2461de3ca2076e0f524b6d74c75e86edb9841a8f`.
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

The remaining 67 review items currently have no field-level candidate
locator: `development_status` and `catalog_status` each have 23 missing
pairs, while `company`, `approval_date`, and `approval_jurisdictions` each
have 7 missing pairs. FDA Purple Book pages now provide candidate locators
for the FDA member, U.S. applicant, and original U.S. approval date of all
16 FDA-jurisdiction rows; two approval-date candidates conflict with the
catalog seed and remain explicitly partial pending adjudication. These
candidates do not establish complete global jurisdiction or current
marketing status.
Their entry-level `source_url` values are retained as seed context only and
cannot support an approval, withdrawal, jurisdiction, or sponsor claim by
themselves. Before these fields are used in a paper result or a released
catalog, add a locator to the relevant regulator decision, label, or other
first-party record, record the jurisdiction and effective date, and complete
the same independent review and provenance checks as the eight core fields.

The automatic value pre-screen found 55 matches among 192 eligible candidate
values (`0.2865`). This is a triage signal only: PDFs and page structure can
hide values, terminology can differ, and no match is treated as a verified
claim. All candidate locators and values remain pending independent human
source review.
