# ADR-006 — Numerics and Legacy Conversion

Owner: Ali Shariati
Status: Accepted

Evidence stores prices, ratios, and R values as scaled integers.
Float values from legacy inputs are converted through an explicit versioned policy and rejected when outside tolerance.
P0 does not freeze entry-order semantics; any P1 interim outcome assumption is versioned and tainted `PROXY_OUTCOME` until the owner defines the real entry rule.
