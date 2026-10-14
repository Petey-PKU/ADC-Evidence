# ADC-Evidence v0.7.0

v0.7.0 changes the public runtime baseline from the ten-record demo seed to the
user-authorized public snapshot `adc_public_2026-09-30.db`, bundled as the tracked
archive `data/processed/adc_public_2026-09-30.db.zip`.

The application now:

- reads the public snapshot by default;
- keeps the snapshot and generated vector index on the mounted data volume;
- skips demo-seed synchronization for an existing public snapshot;
- fails clearly when the snapshot is missing, empty, or still looks like the ten-record demo;
- rebuilds the hashing retrieval index when its corpus version does not match the snapshot;
- keeps the ten-record seed available only through an explicit development path.

The package version is `0.7.0`, while v0.6 schema, benchmark, policy, and
evaluation identifiers remain unchanged so historical reports stay reproducible.
The release tag is `v0.7.0`.
