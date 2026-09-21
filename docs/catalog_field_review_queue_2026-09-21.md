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

The current packet contains 244 candidate source locators covering 241 unique
ADC-field pairs. They are hints for
human checking and are not accepted as field-level evidence until a reviewer
records a source locator, a controlled verdict, and an independent human
review origin. The packet SHA-256 is
`2ef3112223180c9da92b30e2d06d44d08f8dffd2b4d599c404390a9f12a31af2`; its
manifest SHA-256 is
`6afe4614cb896eef9428a7bfcbf7b3c6c6ec77058e28c8ab4e15c36f28f9b216`.

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
`bc591f91079c825a76b5612903e79ee78ed28dddf9661e8622fb2c3a8b63f69a`.
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

The remaining 58 review items currently have no field-level candidate
locator: `development_status` and `catalog_status` each have 23 missing
pairs, while `company`, `approval_date`, and `approval_jurisdictions` each
have 4 missing pairs. FDA Purple Book pages now provide candidate locators
for the FDA member, U.S. applicant, and original U.S. approval date of all
16 FDA-jurisdiction rows. NMPA/PMDA government records add candidate
locators for three non-FDA rows; their dates remain partial where the source
is a notice or review-report date. Two FDA approval-date candidates conflict
with the catalog seed and remain explicitly partial pending adjudication.
These candidates do not establish complete global jurisdiction or current
marketing status.
Their entry-level `source_url` values are retained as seed context only and
cannot support an approval, withdrawal, jurisdiction, or sponsor claim by
themselves. Before these fields are used in a paper result or a released
catalog, add a locator to the relevant regulator decision, label, or other
first-party record, record the jurisdiction and effective date, and complete
the same independent review and provenance checks as the eight core fields.

The automatic value pre-screen found 54 matches among 185 eligible candidate
values (`0.2919`). This is a triage signal only: PDFs and page structure can
hide values, terminology can differ, and no match is treated as a verified
claim. All candidate locators and values remain pending independent human
source review.
