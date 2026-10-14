# Public snapshot distribution

The v0.7 application needs the public SQLite snapshot and its matching retrieval index.
The user-authorized database archive is tracked directly in `main`; this release asset
remains an optional fallback for environments where the repository archive cannot be used. It contains the
bundled application, database, index, catalog, benchmark manifest, and
`RELEASE_MANIFEST.json` checksums.

## For a fresh clone

The normal path is now a clone followed by the default launcher:

```powershell
python -m adc_evidence.deploy
```

If the tracked archive cannot be used and the `v0.7.0` release asset is available, run this
from the repository root:

```powershell
python scripts/install_public_release.py `
  --tag v0.7.0 `
  --asset adc-public-2026-09-30.zip
python -m adc_evidence.deploy
```

The installer downloads the archive from the GitHub Release, verifies every file with the
embedded manifest, and installs only the database and retrieval-index files into the
checkout. Use `--force` only when deliberately replacing an existing snapshot. It does
not call PubMed, ClinicalTrials.gov, ADCdb, or a model API.

The same archive can run independently of a Git checkout:

```powershell
python -m zipfile -e adc-public-2026-09-30.zip adc-public-2026-09-30
cd adc-public-2026-09-30
python -m pip install -e .
python scripts/run_public_release.py
```

The tracked snapshot archive is the canonical v0.7 runtime data. The optional release
archive must still use the same database checksum and matching retrieval index; generated
indexes and raw source responses remain outside Git history.
