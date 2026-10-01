# ADR-003 — Identity and Idempotency

Owner: Ali Shariati
Status: Accepted

Use domain-tagged SHA-256 IDs over acyclic canonical preimages.
Request-keyed human/client writes are idempotent.
Candidate occurrence identity is separate from dataset/version-bound candidate identity.
Evaluation context pins label/macro/peer inputs.
Same-manifest determinism and cross-dataset semantic-prefix invariance are distinct tests.
