# Offline research package gate (2026-09-21)

The package was rebuilt from code commit `f3beaf950c197751949e92a57d295c916618ddf0`
using the public snapshot and matching vector index:

```powershell
$env:PYTHONPATH="src"
python scripts/package_public_release.py `
  --research-only `
  --database data/processed/adc_public_2026-09-30.db `
  --index-path artifacts/vector_index/public_2026-09-30 `
  --benchmark-manifest data/annotations/public_benchmark_v1.manifest.json `
  --benchmark-questions data/annotations/public_benchmark_v1.jsonl `
  --candidate-locators data/public/catalog_source_locator_candidates.jsonl `
  --output .test_tmp/adc-public-research-only-f3beaf9.zip `
  --as-of 2026-09-30
python scripts/verify_public_release.py .test_tmp/adc-public-research-only-f3beaf9.zip
```

The archive is 42,156,306 bytes with SHA-256
`ff729f1e478c59c60ca0645e8a4efacf9e0cbb41969cbd5486e7517886ec6757`.
Verification checked 79 files, found zero absolute database paths, and found
the bundled application, public benchmark questions, and candidate locator
file. The database and index are bound to retrieval corpus
`corpus_bf154bd752280b20b6ea0ad9cab8dde06e65062276209ae655bf27de49efc1ca`.

After extraction, the following smoke checks passed:

```powershell
python -I .test_tmp/release-smoke-f3beaf9/scripts/run_public_release.py --check
python -I .test_tmp/release-smoke-f3beaf9/scripts/run_public_release.py `
  --question "T-DXd 的靶点和载荷是什么？"
```

The launcher reported `offline_only=true` and `backend=extractive`; the query
returned `answered`, route `structured_fact`, and supported `HER2` and `Dxd`
with two citations. No project model API or model download was used. This
demonstrates direct offline use after extraction and does not establish
clinical validity or source completeness.

The package remains `research_only` with `redistribution_allowed=false`.
No GitHub Release should be created until the source-content licence review
and a v2 content-free redistribution attestation with per-source approved
license entries are complete. The attestation format is documented in
`docs/redistribution_attestation.md`.
