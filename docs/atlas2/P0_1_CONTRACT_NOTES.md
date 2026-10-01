# P0-1 Core Contract Closure

Owner: Ali Shariati
Status: CLOSED — implementation and independent review complete

## Closed in this slice

- ACE-1 accepts only null/bool/int/string/list/dict, has a consistent 16-container nesting limit, a 64 KiB encoded limit, NFC string encoding, ASCII schema keys, int64 integers, and domain-tagged SHA-256.
- Typed IDs can enforce expected prefixes; current data contracts enforce the prefixes explicitly frozen by the design: obs, comp, fbar, fqt, ds, and the fact-family set.
- Stored contract text must already be NFC-normalized; canonical normalization cannot silently collapse two differently stored strings.
- UTC microseconds have one supported UTC datetime range (year 0001 through 9999), with exact pre/post-epoch arithmetic.
- Scaled numeric converters use exact half-even arithmetic, reject floats, and accept only plain ASCII decimal text or Decimal values.
- Taint masks derive their valid-bit mask from the enum and reject unknown/boolean/noninteger values.
- P0 architecture tests reject direct legacy/broker/network/importlib imports, dynamic import calls, order APIs, and runtime side-effect loading of legacy Atlas/MetaTrader5.
- Raw/model validation enforces hashes, typed IDs, timestamp ranges, integer ranges, availability-basis shape, OHLC/quote invariants, closed vocabularies, and DatasetMembership fact-kind/prefix consistency.

## Deliberately deferred to the stage that owns the rule

- validate() remains explicit because the frozen design specifies frozen dataclasses with validate(). P0-2 Store must validate before persistence.
- Bar availability vs close-time, observation availability, HTF propagation, timeframe span/alignment, and broker-grid rules belong to P0-4 Data/Views, where all required inputs are available.
- Candidate/evaluation/occurrence identity preimages belong to P0-6/P0-7; generic make_id does not invent them.
- Holdout session framing belongs to P0-3 Registry/Holdout; retries must reuse the same grant/preregistration session identity.
- Legacy float tolerance/versioning remains deferred to conditional legacy import.
- Entry-order semantics remain owner-unresolved and do not enter P0.

## Verification

- Python 3.14: 30 Atlas v2 tests PASS.
- Python 3.12: 30 Atlas v2 tests PASS.
- Legacy atlas/ unchanged.
- No broker/network execution path introduced.

## Independent review closure

Claude read-only review returned PASS-WITH-FIXES with two remaining P0-1 items: DatasetMembership fact-kind/prefix consistency and a stronger dynamic-import guard. Both were fixed and the full suite re-ran cleanly on Python 3.14 and Python 3.12. No further P0-1 review loop is required.
