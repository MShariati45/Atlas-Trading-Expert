# Atlas v2 P1-5 — Owner H4 Direction Gate

Owner: Ali Shariati
Status: CLOSED — implemented, reviewed, and validated

## Authority

This slice carries forward two already-recorded Atlas rules:

- Atlas v2 design: Track A is the owner arm using human H4 labels, and the H4 context gate measures direction.
- Frozen RC10 strategy authority: H4 direction is mandatory; an M15 candidate must align with the owner-validated H4 impulse direction; H1 remains context-only.

No new H4 trading rule is introduced here.

## Included

- Consume the same immutable, pinned H4 label evidence already used by P1-4.
- Require an OPERATIONAL LabelSetPin selected with `latest-authorized-owner-v1` before H4 evidence can authorize Track A.
- Preserve all P1-4 causal/sealed/source-identity rules.
- LONG + BULLISH and SHORT + BEARISH -> H4_CONTEXT PASS.
- Opposite directional pairing -> H4_CONTEXT FAIL.
- RANGE / TRANSITION -> NOT_EVALUABLE; do not invent a directional trade decision.
- Abstention, missing/ambiguous/non-causal/unsealed evidence -> NOT_EVALUABLE.
- Store owner H4 confidence and declared probability when present.
- Keep all execution authority absent.

## Excluded

- No automatic H4 structure inference.
- No engine/research label promotion to owner authority.
- No H1 hard gate.
- No Fibonacci entry permission.
- No M15 structure classifier changes.
- No session/news/spread implementation.
- No broker, Demo or Live execution.
