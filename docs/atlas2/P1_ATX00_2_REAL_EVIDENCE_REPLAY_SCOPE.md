# Atlas v2 ATX00-2 — Real Evidence Binding + Chronological Account Replay

Owner: Ali Shariati
Status: CLOSED — adapter/account-replay slice implemented, reviewed, and validated; ATX-00 overall remains open pending real broker evidence
Research alias: ATX-00
Authority: LAB ONLY / NO ORDER

## Purpose

ATX00-2 bridges the golden fidelity primitives from ATX00-1 to immutable Atlas data and normalized broker/account evidence without introducing any broker SDK, execution authority, or invented trading semantics.

## Included

- Bind sealed Atlas v2 DatasetVersion quote evidence through PIT MarketView.
- Require quote source sequence for fidelity replay; do not invent multiplicity/order.
- Verify every source observation used by a dataset agrees with the dataset clock-profile binding.
- Bind dataset clock_profile_id and tzdata_version into quote-evidence identity.
- Content-digest the complete causal quote slice.
- Define a normalized external execution-evidence contract tied to one immutable source SHA-256.
- Require explicit timestamp + globally ordered source sequence for each execution event; event IDs and source locators must be unique.
- Replay ENTRY/EXIT fills chronologically with actual filled volume, FIFO matching within trade ID, and explicit per-exit account-currency conversion.
- Normalize commission/swap as non-negative incurred costs before replay.
- Track explicit risk commitments, peak concurrent risk, cap-breach episodes, cash adjustments, and management request/ack/reject evidence; commitment/request IDs cannot be reused.
- Stop requests require an open trade; ACK activates the requested stop only while the trade is still open; fully closed trades clear active stop state and their trade_id cannot be reopened within the replay.
- Content-digest normalized execution evidence and chronological account replay results.
- Fail closed on missing chronology, mismatched source blobs, unmatched exits, duplicate risk identity, and unmatched management acknowledgement.

## Explicit exclusions

- No MetaTrader SDK import or network access.
- No production OutcomeAttachment resolver.
- No inference of broker server timezone/offset from filenames or bars.
- No raw broker export parser until an actual export format is supplied and frozen.
- No hidden spread/slippage/commission/swap defaults.
- No owner risk cap or reset time invented by this slice.
- No confirmation that ATX-00 is complete.
- No Demo/Live/order authority.

## Current external-data readiness

A read-only scan of the current Mac Atlas project/Desktop/Downloads/Documents found legacy bar/event CSVs, but no identifiable MT5 deal/fill statement, tick/quote export, or account-history export suitable for real ATX-00 reconciliation.

Therefore this slice prepares and validates the internal adapter/replay boundary now. The confirmatory real-data run remains blocked only on supplying or exporting the actual broker/account evidence and explicit clock/profile mapping.
