# Offline research package gate (2026-09-21)

The package was rebuilt from code commit `a715a25de696072a01689a96c71bc81c8acdba2a`
using the public snapshot and matching vector index:

```powershell
$env:PYTHONPATH="src"
python scripts/package_public_release.py `
  --research-only `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --output .test_tmp/adc-public-research-only-a715a25.zip
python scripts/verify_public_release.py .test_tmp/adc-public-research-only-a715a25.zip
```

The archive is 42,149,373 bytes with SHA-256
`ad731b636fe0c1cd6c233a1411c1b48b2fe63145ac6cc5a174a66cb44894f7be`.
Verification checked 79 files, found zero absolute database paths, and found
the bundled application, public benchmark questions, and candidate locator
file. The database and index are bound to retrieval corpus
`corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca`.

After extraction, the following smoke checks passed:

```powershell
python -I .test_tmp/release-smoke-a715a25/scripts/run_public_release.py --check
python -I .test_tmp/release-smoke-a715a25/scripts/run_public_release.py `
  --question "T-DXd 的靶点是什么？"
```

The launcher reported `offline_only=true` and `backend=extractive`; the query
returned `answered`, route `structured_fact`, and the supported target `HER2`.
This demonstrates direct offline use after extraction and does not establish
clinical validity or source completeness.

The package remains `research_only` with `redistribution_allowed=false`.
No GitHub Release should be created until the source-content licence review
and a content-free redistribution attestation are complete.
