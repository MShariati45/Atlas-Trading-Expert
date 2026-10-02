# Atlas v2 P0-9 — Hardware Baseline

Owner: Ali Shariati
Recorded: 2026-10-01 (local development host)

This is descriptive evidence only. P0 defines no hardware pass/fail threshold.

- Platform: Darwin 24.6.0
- Machine architecture: x86_64
- Python runtime observed: 3.14.7
- Logical CPU count: 8
- Physical memory: 8,589,934,592 bytes (~8.0 GiB)
- Filesystem total capacity observed at Atlas repo: 121,018,208,256 bytes (~112.7 GiB)
- Filesystem free capacity observed: 15,994,904,576 bytes (~14.9 GiB)

The runtime hardening code also supports recording a content-derived immutable hardware baseline inside an Atlas evidence store. Disk-free observations are expected to change over time and therefore do not act as identity-independent acceptance criteria.
