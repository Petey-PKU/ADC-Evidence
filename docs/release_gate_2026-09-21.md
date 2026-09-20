# Offline research package gate (2026-09-21)

The package was rebuilt from code commit `683f999cbe1a001f5b81e42979672f74be3d4ced`
using the public snapshot and matching vector index:

```powershell
$env:PYTHONPATH="src"
python scripts/package_public_release.py `
  --research-only `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --output .test_tmp/adc-public-research-only-683f999.zip
python scripts/verify_public_release.py .test_tmp/adc-public-research-only-683f999.zip
```

The archive is 42,150,570 bytes with SHA-256
`54a614913b16984f04a5e3358d5660c03a41e75bd81ff223a2bd7e416a53e78c`.
Verification checked 79 files, found zero absolute database paths, and found
the bundled application, public benchmark questions, and candidate locator
file. The database and index are bound to retrieval corpus
`corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca`.

After extraction, the following smoke checks passed:

```powershell
python -I .test_tmp/release-smoke-683f999/scripts/run_public_release.py --check
python -I .test_tmp/release-smoke-683f999/scripts/run_public_release.py `
  --question "T-DXd 的靶点是什么？"
```

The launcher reported `offline_only=true` and `backend=extractive`; the query
returned `answered`, route `structured_fact`, and the supported target `HER2`.
This demonstrates direct offline use after extraction and does not establish
clinical validity or source completeness.

The package remains `research_only` with `redistribution_allowed=false`.
No GitHub Release should be created until the source-content licence review
and a v2 content-free redistribution attestation with per-source approved
license entries are complete. The attestation format is documented in
`docs/redistribution_attestation.md`.
