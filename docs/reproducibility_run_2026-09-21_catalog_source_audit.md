# Reproducibility record: public catalog source audit (2026-09-21)

This record binds the public catalog source-locator update to public code commit
`646f7568dc227ad1d70e0bc4374b9d5d89836a54` on branch
`research/v0.6-freeze`. The
update adds provisional status locators for all 23 catalog rows in addition to
the company, approval date, and approval jurisdiction locators added for
`adc_006`, `adc_017`, `adc_018`, and `adc_020`. These are source-review leads
only; no human verdict or confirmed catalog value was added.

## Inputs and hashes

| Artifact | SHA-256 or value |
|---|---|
| Public catalog (`data/public/marketed_adc_catalog.csv`) | `sha256:97a21b0f104ee530783c1aa367cc28f95643680e82c54e6e57f83d5f195e692c` |
| Candidate locator manifest hash | `sha256:fc17c58e8a63f6473794542d969779eeefbc55aff1f6b406eea8f7447a3260fa` |
| Source-content audit report | `sha256:6924542a309592e58f2f49289f8d3fedca04f31953bdcf04fcc2aa67921c1184` |
| Field-review packet | `sha256:4085e3cc1b5489bd600abcd4ca825680a3cabeab3fd4bd1e7ae09e78b1504880` |
| Field-review manifest | `sha256:9e53920b026a3a08f7fdb3959666ab43e21aad24775117a9469298f2c3a211e7` |

The candidate file contains 302 rows covering all 299 unique ADC-field pairs.
All 299 review items remain pending independent primary-source review. The
`development_status` and `catalog_status` candidates are explicitly
provisional: approval or withdrawal records do not automatically establish
current global marketing status. The automatic content triage found 68
matches among 222 eligible candidate values (`0.3063`); this is not a
correctness metric.

## Commands

```powershell
$env:PYTHONPATH="src"
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
python scripts/audit_public_catalog_sources.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --output .test_tmp/public_catalog_source_audit_2026-09-21_status.json
python scripts/build_catalog_field_review_packet.py `
  --output .test_tmp/catalog_field_review_status.jsonl `
  --manifest .test_tmp/catalog_field_review_status.manifest.json
python scripts/validate_catalog_field_review.py `
  --packet .test_tmp/catalog_field_review_status.jsonl `
  --manifest .test_tmp/catalog_field_review_status.manifest.json `
  --catalog data/public/marketed_adc_catalog.csv
python -m unittest discover -s tests -p "test_*.py" -q
python scripts/audit_public_hygiene.py
python scripts/audit_paper_readiness.py `
  --public-dataset-audit .test_tmp/public_dataset_audit_2026-09-21_with_raw.json `
  --public-catalog-source-audit .test_tmp/public_catalog_source_audit_2026-09-21_status.json `
  --output .test_tmp/paper_readiness_status.json
```

## Results and boundaries

- Field-review packet validation: `passed`; 299 pending items, 0 completed.
- Unit tests: 239 passed, 4 skipped.
- Public hygiene: `clean`; 223 tracked files scanned, no findings.
- Paper-readiness audit: `not_ready_for_submission`; public dataset remains
  `partial`, and real independent human labels plus a separately frozen,
  access-controlled holdout are still required.
- The candidate locators come from issuer filings, an issuer announcement,
  and an issuer press release. Their announcement dates are not silently
  treated as regulatory decision dates. Private databases, reviewer records,
  credentials, and restricted full text were not read or copied into the
  public repository.
