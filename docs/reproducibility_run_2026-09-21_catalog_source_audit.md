# Reproducibility record: public catalog source audit (2026-09-21)

This record binds the non-FDA regulatory-locator update to public code commit
`d7c33d33eabd266fdda6b0dff698069f7d935b40` on branch
`research/v0.6-freeze`. The update adds candidate locators for company,
approval date, and approval jurisdiction for `adc_006`, `adc_017`, `adc_018`,
and `adc_020`. These are source-review leads only; no human verdict or
confirmed catalog value was added.

## Inputs and hashes

| Artifact | SHA-256 or value |
|---|---|
| Public catalog (`data/public/marketed_adc_catalog.csv`) | `sha256:97a21b0f104ee530783c1aa367cc28f95643680e82c54e6e57f83d5f195e692c` |
| Candidate locator manifest hash | `sha256:d581ecbd4b8458d9b987207c97cf676e8a4111b3ffc3b6e1ca35c490d901432d` |
| Source-content audit report | `sha256:86edcff96c8fd58599e405c0465236f950340c116643babc2b66ccf353c232d5` |
| Field-review packet | `sha256:40f78d722492443efe7039106072d06252eca671ead22fb46f1bbc031fb1d805` |
| Field-review manifest | `sha256:dc2d2680c37de0b464e6de7cebff5f14c392e10566576524bb305772048dcc6f` |

The candidate file contains 256 rows covering 253 unique ADC-field pairs. All
299 review items remain pending independent primary-source review. Candidate
locators now cover all 23 rows for `company`, `approval_date`, and
`approval_jurisdictions`; `development_status` and `catalog_status` still have
23 missing pairs each. The automatic content triage found 55 matches among
188 eligible candidate values (`0.2926`); this is not a correctness metric.

## Commands

```powershell
$env:PYTHONPATH="src"
$env:HTTP_PROXY="http://127.0.0.1:7890"
$env:HTTPS_PROXY="http://127.0.0.1:7890"
python scripts/audit_public_catalog_sources.py `
  --catalog data/public/marketed_adc_catalog.csv `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --output .test_tmp/public_catalog_source_audit_2026-09-21_after4.json
python scripts/build_catalog_field_review_packet.py `
  --output .test_tmp/catalog_field_review_after4.jsonl `
  --manifest .test_tmp/catalog_field_review_after4.manifest.json
python scripts/validate_catalog_field_review.py `
  --packet .test_tmp/catalog_field_review_after4.jsonl `
  --manifest .test_tmp/catalog_field_review_after4.manifest.json `
  --catalog data/public/marketed_adc_catalog.csv
python -m unittest discover -s tests -p "test_*.py" -q
python scripts/audit_public_hygiene.py
python scripts/audit_paper_readiness.py `
  --public-dataset-audit .test_tmp/public_dataset_audit_2026-09-21_with_raw.json `
  --public-catalog-source-audit .test_tmp/public_catalog_source_audit_2026-09-21_after4.json `
  --output .test_tmp/paper_readiness_after4.json
```

## Results and boundaries

- Field-review packet validation: `passed`; 299 pending items, 0 completed.
- Unit tests: 239 passed, 4 skipped.
- Public hygiene: `clean`; 222 tracked files scanned, no findings.
- Paper-readiness audit: `not_ready_for_submission`; public dataset remains
  `partial`, and real independent human labels plus a separately frozen,
  access-controlled holdout are still required.
- The candidate locators come from issuer filings, an issuer announcement,
  and an issuer press release. Their announcement dates are not silently
  treated as regulatory decision dates. Private databases, reviewer records,
  credentials, and restricted full text were not read or copied into the
  public repository.
