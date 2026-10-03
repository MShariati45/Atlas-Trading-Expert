# Atlas v2 ATX00-1 — Replay / Accounting Fidelity Notes

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, and dual-runtime validation complete

## Implementation

- Added `atlas2.research.atx00`.
- Added deterministic OHLC barrier handling that returns AMBIGUOUS when both stop and target are touched in one bar.
- Adverse gap-through-stop uses the scenario's first executable bar price rather than the stale stop.
- Added stop modification state where only ACKED changes become active.
- Added explicit source-sequence requirement for otherwise ambiguous same-time stop updates and fills.
- Added FIFO partial-fill accounting with explicit account-currency cash conversion factor and explicit costs.
- Added half-open risk-window and concurrent-risk primitives.
- Added exact account-cash reconciliation.
- Added historical feature availability/confirmation causality check.
- Added a ResearchRegistry-compatible ATX-00 preregistration payload.
## Golden self-check

`python -m atlas2.research.atx00 --self-check` currently covers:

1. same-bar stop/target ambiguity;
2. adverse gap-through-stop;
3. stop request before acknowledgement;
4. rejected stop update;
5. partial fills and cost reconciliation;
6. explicit pair/account-currency conversion factor;
7. half-open daily/risk boundary semantics;
8. pending + open concurrent risk;
9. account balance reconciliation;
10. historical feature confirmation availability.

The packet remains explicitly labeled `ATX00-1` and lists remaining real-data/account integration prerequisites.

## Scope boundary

This is not the production outcome resolver and does not claim ATX-00 is complete. It creates testable primitives for the source pack's manually specified fidelity cases without inventing broker behavior or unresolved owner semantics.

## Independent review

The first review found one high-severity chronology bug in fill accounting plus two design gaps: executable BID/ASK basis for short exits and accidental default CONFIRMATORY registration. All were fixed. A re-review returned **PASS**.

A final review after additional hardening also returned **PASS** with no concrete blocker. Optional findings were addressed where useful: target-gap handling, positive price/stop validation, int64 output validation, feature timestamp consistency, duplicate risk identities, short-side and partial-fill coverage, and explicit adapter/accounting boundaries.

## Final validation

- ATX00 fidelity tests: **21/21 PASS** on Python 3.14 and Python 3.12.
- ATX00 + ResearchRegistry focused suite: **34/34 PASS + 21 subtests** on both runtimes.
- Full Atlas v2 suite: **235/235 PASS + 242 subtests** on Python 3.14 and Python 3.12.
- `python3 -m compileall -q atlas2`: PASS.
- `git diff --check`: PASS.
- Deterministic ATX00 self-check: PASS.
- Trading authority introduced: **NO**.
