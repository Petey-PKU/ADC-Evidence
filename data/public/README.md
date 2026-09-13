# Public ADC dataset

This directory contains a reproducible, redistributable catalog seed for the
public ADC-Evidence application. It is deliberately separate from the private
SQLite database and private expert-review exports.

## Scope

`marketed_adc_catalog.csv` is a **candidate global regulatory catalog**. The
current snapshot window is `2026-06-30`, the latest complete public inventory
used while this release is being prepared. The requested target window is
`2026-09-30`; records that changed after the current window must be added only
after a source check. The catalog contains products that had received approval
by the snapshot date, including historically approved products that were later
withdrawn. Use `catalog_status` to distinguish `marketed`, `withdrawn`, and
`approved_not_marketed` records.

The catalog is a public starting point, not a claim that every field has been
independently verified. `verification_status=pending_primary_check` means a
primary regulator label or registry record still needs to be checked before a
paper uses the field as a gold-standard fact.

## Data policy

- The CSV contains structured facts and source links only; it contains no
  reviewer identities, private notes, API keys, raw API responses, or model
  outputs.
- Publication status is jurisdiction-specific. A product marked `marketed`
  means marketed in at least one listed jurisdiction at the snapshot window;
  it does not imply approval in every country.
- The catalog source is a secondary inventory used to make the initial scope
  reproducible. FDA, EMA, PMDA, NMPA, or other regulator sources must be bound
  to each record before a release is treated as a regulatory gold set.
- Literature abstracts and trial records are collected separately by the
  public builder. Abstract redistribution and any full text require a source
  license check; the builder records URLs, retrieval time, and hashes.

## Build a local database

From the repository root:

```powershell
$env:PYTHONPATH="src"
python scripts/build_public_dataset.py --catalog data/public/marketed_adc_catalog.csv
```

The generated SQLite database, raw responses, and retrieval index stay in local
ignored paths. The command accepts `--as-of YYYY-MM-DD` and records the actual
source windows in its manifest. It does not call a generative model.

To run the Streamlit app against a generated snapshot without replacing the
demo database, set these variables before starting Streamlit:

```powershell
$env:ADC_DATABASE_PATH="data/processed/adc_public_2026-09-30.db"
$env:ADC_SEED_PATH="data/public/marketed_adc_catalog.csv"
$env:ADC_VECTOR_INDEX_PATH="artifacts/vector_index/public_2026-09-30"
streamlit run src/adc_evidence/app.py
```
