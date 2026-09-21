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

The current packet contains 256 candidate source locators covering 253 unique
ADC-field pairs. They are hints for
human checking and are not accepted as field-level evidence until a reviewer
records a source locator, a controlled verdict, and an independent human
review origin. The packet SHA-256 is
`40f78d722492443efe7039106072d06252eca671ead22fb46f1bbc031fb1d805`; its
manifest SHA-256 is
`dc2d2680c37de0b464e6de7cebff5f14c392e10566576524bb305772048dcc6f`.

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
`86edcff96c8fd58599e405c0465236f950340c116643babc2b66ccf353c232d5`.
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

The remaining 46 review items currently have no field-level candidate
locator: `development_status` and `catalog_status` each have 23 missing
pairs, while `company`, `approval_date`, and `approval_jurisdictions` now
have candidate locators for all 23 rows. FDA Purple Book pages now provide
candidate locators for the FDA member, U.S. applicant, and original U.S.
approval date of all 16 FDA-jurisdiction rows. NMPA/PMDA government and
first-party issuer records now provide candidate locators for all seven
non-FDA rows; dates remain partial where the source is an announcement,
notice, or review-report date. Two FDA approval-date candidates conflict
with the catalog seed and remain explicitly partial pending adjudication.
These candidates do not establish complete global jurisdiction or current
marketing status.
Their entry-level `source_url` values are retained as seed context only and
cannot support an approval, withdrawal, jurisdiction, or sponsor claim by
themselves. Before these fields are used in a paper result or a released
catalog, add a locator to the relevant regulator decision, label, or other
first-party record, record the jurisdiction and effective date, and complete
the same independent review and provenance checks as the eight core fields.

The automatic value pre-screen found 55 matches among 188 eligible candidate
values (`0.2926`). This is a triage signal only: PDFs and page structure can
hide values, terminology can differ, and no match is treated as a verified
claim. All candidate locators and values remain pending independent human
source review.
