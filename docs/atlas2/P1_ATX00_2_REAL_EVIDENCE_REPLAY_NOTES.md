# Atlas v2 ATX00-2 — Real Evidence Binding + Account Replay Notes

Owner: Ali Shariati
Status: CLOSED — implementation, independent review, and dual-runtime validation complete; ATX-00 overall remains open pending real broker evidence

## Implementation

- Added `atlas2.research.atx00_evidence`.
- Added sealed-dataset and child-digest verification before quote replay.
- Added clock-profile consistency verification across dataset member observations.
- Added causal quote binding through existing MarketView / holdout guard.
- Quote replay requires explicit source_seq and produces a deterministic semantic digest.
- Added normalized execution evidence bound to one lowercase source SHA-256 with unique event ID, locator, and globally ordered source sequence.
- Added deterministic chronological account replay for fills, costs, cash adjustments, explicit risk commitments, and stop request/ack/reject evidence.
- Replay policy is explicit and digest-bound: FIFO within trade ID; EXIT direction means original position direction; account-currency conversion is required only on realized EXIT_FILL events.
- Trade IDs cannot reopen after full close; stop/request and risk commitment identities cannot be reused; unresolved requests and active stops are surfaced in the replay result.
- Risk-cap violations are counted as breach episodes rather than every event while above cap.
- Replay output remains a Lab research record, not an OutcomeAttachment or trading decision.

## Review and validation

Initial independent review found three concrete execution-evidence/replay gaps: canonical source hash enforcement, stop lifecycle/result visibility, and implicit FIFO/entry-conversion semantics. After those fixes, a second review found two further blockers: replay accepted a forged bundle and trade IDs could reopen after full close. Both were fixed. The final independent re-review returned **PASS** with no blocker; its one low int64 open-volume note was also fixed.

Final validation:
- Focused ATX00 evidence/fidelity/registry suite, Python 3.14: **46/46 PASS + 21 subtests**.
- Focused ATX00 evidence/fidelity/registry suite, Python 3.12: **46/46 PASS + 21 subtests**.
- Full Atlas v2 suite, Python 3.14: **247/247 PASS + 242 subtests**.
- Full Atlas v2 suite, Python 3.12: **247/247 PASS + 242 subtests**.
- `python3 -m compileall -q atlas2`: PASS.
- `git diff --check`: PASS.
- Trading/order authority introduced: **NO**.

## Real-data dependency

No suitable real broker fill/tick/account export was found in the current Atlas project, Desktop, Downloads, or Documents scan. The adapter is ready for a frozen export, but no fake or legacy-derived fill stream will be substituted.

The raw broker adapter must map a real export into the normalized v1 event contract and preserve:
- raw source SHA-256,
- row/event locator,
- broker timestamp,
- source sequence/deal identity,
- fill side, price, volume,
- account-currency conversion evidence,
- commission/swap cost normalization,
- management request/ack/reject identity,
- explicit clock mapping.

ATX-00 overall remains OPEN until real evidence is replayed and reconciled against the source account/broker log.
