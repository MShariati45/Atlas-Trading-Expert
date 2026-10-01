# ADR-004 — Append-Only Evidence and Sealing

Owner: Ali Shariati
Status: Accepted

Raw detector capture commits before downstream evaluation.
Evidence uses append-only rows; corrections supersede rather than overwrite.
Aggregate children are sealed with a child-set digest and cannot grow after sealing.
Run completion is an immutable terminal row.
Audit hashing is tamper-evident relative to an external checkpoint, not tamper-proof.
