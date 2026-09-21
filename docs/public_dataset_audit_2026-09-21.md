# Public dataset audit (2026-09-21)

The public snapshot was audited with an as-of date of `2026-09-30`:

```powershell
$env:PYTHONPATH="src"
python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --as-of 2026-09-30 `
  --output .test_tmp/public_dataset_audit_2026-09-21.json
```

The database hash is bound in the JSON report; the report SHA-256 is
`b6263077c5e59039a1bc9fe7058b2cf32db1dc2cf65bd3841de14168080a06cd`.
The snapshot contains 23 ADCs, 3,503 trials, 1,410 documents, and 6,754
entity links. No duplicate ADC, trial, or document identifiers were found;
there were no orphan links, unknown ADC entity IDs, duplicate logical link
groups, or unmatched aliases. All stored trial and document URLs were HTTPS
and distinct within their table.

Entity linkage is still a coverage result rather than a semantic gold label:
2,268 trial links cover 1,739 distinct trials and 4,486 document links cover
1,387 distinct documents. Every ADC has at least one trial and document link,
but only the captured records are represented.

Source coverage remains explicitly incomplete:

| Source | Run status | Collected / expected | Coverage state |
|---|---:|---:|---|
| ClinicalTrials.gov | partial | 2,000 / 13,978 | partial (`0.143082`) |
| PubMed | partial | 1,015 / 165,105 | partial (`0.006148`) |
| ADCDB | skipped | no denominator | unknown |

The date audit found seven PubMed records with issue dates after the requested
cutoff. They remain `pending_review` because the raw source root was not
provided; issue date, electronic publication date, and indexing date must be
distinguished before an as-of claim is made. The overall dataset status is
`partial`, and ADC fact source quality remains `needs_review` because current
facts are still marked `curated_seed_not_independently_reviewed`.

The checksum-bound raw snapshot was then supplied to the same audit:

```powershell
python scripts/audit_public_dataset.py `
  --database data/processed/adc_public_2026-09-30.db `
  --as-of 2026-09-30 `
  --raw-root data/raw/public_2026-09-30 `
  --output .test_tmp/public_dataset_audit_2026-09-21_with_raw.json
```

The raw-bound report SHA-256 is
`d2c4da6fc481528a53649e0b702178b53c26216794cfdb38f33f5d5195758099`.
All seven raw XML files matched the database checksum and contained one
matching PMID. Six records have an electronic publication date on or before
the cutoff; one record (`PMID 42233446`) has only pre-cutoff PubMed/Entrez
indexing dates and also carries a chronology warning because its acceptance
date follows those indexing dates. These seven records remain
`candidate_pending_review`; the audit does not silently convert them into
eligible historical evidence.
