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

The current packet contains 161 candidate source locators. They are hints for
human checking and are not accepted as field-level evidence until a reviewer
records a source locator, a controlled verdict, and an independent human
review origin. The packet SHA-256 is
`e0cc7012aee66eb0d2f925fdd48b8137023c83e312db5532f1de7f5cbe679cae`; its
manifest SHA-256 is
`e2f24dc05b80630962f7eac2b9cb7c1bc8ecf35b2dce72f31ce00bba35e9341c`.

Until the required independent primary and secondary reviews are supplied,
the catalog source-quality gate remains `needs_review` and the project must
not describe these rows as expert-verified or publication-grade gold data.

The scope validator records 21 core ADC rows and two excluded modality rows
(`adc_021` photoimmunoconjugate and `adc_023` recombinant immunotoxin). The
catalog status distribution is 21 core marketed, one extended marketed, and
one extended withdrawn record. These are explicit catalog-scope labels; they
do not independently establish regulatory status.
