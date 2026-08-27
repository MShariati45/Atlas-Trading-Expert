# Atlas v0.13 - Historical Bootstrap & Persisted Runtime

## Implemented
- Read-only historical H4/H1 bootstrap from completed MT5 candles.
- Confirmed local swing extraction and same-type swing compression.
- Initial trend seeding from recent coherent HH/HL or LH/LL structure.
- Persistent JSON state for single-machine demo observation.
- Persisted H4/H1 bar cursors.
- Incremental processing of only newly closed H4/H1 candles after bootstrap.
- Live Fibonacci context generation from persisted H1 state when H4/H1 are aligned.
- No order execution in this runtime.

## Safety behavior
- MT5 forming candle at position 0 remains excluded.
- If a coherent bootstrap sequence cannot be found, initialization fails rather than guessing.
- Persisted state prevents repeated historical rescans after restart.
- Production persistence can later replace JSON with SQLite/Postgres/Redis without changing agent interfaces.

## Next milestone
Wire the persisted runtime into the dashboard and multi-symbol event loop, then compare Atlas's real H4/H1/Fibonacci interpretation against selected MT5 demo charts before demo execution is enabled.
