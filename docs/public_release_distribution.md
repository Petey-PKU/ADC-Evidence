# Public snapshot distribution

The v0.7 application needs the public SQLite snapshot and its matching retrieval index.
They are intentionally kept outside Git history. The supported distribution format is a
versioned GitHub Release asset containing the bundled application, database, index,
catalog, benchmark manifest, and `RELEASE_MANIFEST.json` checksums.

## For a fresh clone

After the `v0.7.0` release asset is published, run this from the repository root:

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

## Publication gate

The archive must be published only after the source-license review is complete. The
packager accepts either `--research-only` for local validation or a content-free
`--redistribution-attestation` that records an approved license basis for every source
scope. A research-only archive must remain local and is not a public download.

The current v0.7 snapshot is therefore reproducible locally, but its GitHub download
asset is pending that publication gate. The SQLite file and generated index remain
ignored by Git; the release asset is the place for the large runtime data.
