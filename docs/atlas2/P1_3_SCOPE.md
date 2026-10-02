# Atlas v2 P1-3 — Track A Evaluation + Shadow Integration

Owner: Ali Shariati
Status: CLOSED — implemented, reviewed, and validated

## Goal

Integrate the frozen Owner Track A strategy versions into the immutable evaluation ledger and Shadow/replay surface without inventing unresolved trading semantics.

## Included

- Evaluate C0 and Owner Track A in one fresh, unsealed EvaluationContext before the context is sealed.
- Register the Owner Track A 2R + BE@1.4R baseline and the 2R/no-BE ablation.
- Reuse the existing C0 DATA_QUALITY gate.
- Persist the remaining frozen gate kinds as explicit evidence.
- Where the actual evaluator or owner operational definition is not yet implemented, write NOT_EVALUABLE rather than guessing.
- Keep H1_CONTEXT informational.
- Keep CORRECTION_LOCATION informational/measurement-only and NOT_APPLICABLE until its measurement is implemented.
- Seal the EvaluationContext only after C0 and both Track A arms are complete.
- Surface C0 and both Owner Track A versions through the existing deterministic Shadow report.
- Preserve replay determinism across fresh attempts.

## Required-gate behavior

For Owner Track A:
- required ERROR -> ERROR;
- required FAIL -> REJECT;
- required WAIT / ABSTAIN / NOT_APPLICABLE / NOT_EVALUABLE -> ABSTAIN;
- ACCEPT requires all REQUIRED gates to PASS.

Informational gates never block ACCEPT.

## Current P1-3 gate state

Implemented:
- DATA_QUALITY through the existing C0 evaluator.

Explicitly pending and therefore NOT_EVALUABLE:
- M15_COORDINATION;
- H4_CONTEXT;
- H1_CONTEXT;
- SESSION_DAY;
- NEWS_RISK;
- SPREAD_COST.

Measurement-only pending:
- CORRECTION_LOCATION -> NOT_APPLICABLE.

This means Owner Track A cannot produce ACCEPT in P1-3. That is deliberate and fail-closed.

## Immutability boundary

A P0 context already sealed with C0-only evidence is never retrofitted. P1 replay must evaluate a fresh/unsealed context in a fresh replay store or operate on new forward contexts. Existing P0 evidence remains byte-for-byte immutable.

## Excluded

- No production M15 pattern classifier semantics.
- No H4/H1 gate evaluator.
- No session/news/spread evaluator.
- No production outcome resolver.
- No portfolio sizing.
- No MT5/broker/network path.
- No order, Demo, or Live authority.
