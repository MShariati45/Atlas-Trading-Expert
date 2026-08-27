# H4 Structure Engine v0.2 status

Implemented now:
- Persistent validated H4 state with incremental updates on H4_BAR_CLOSED.
- Multi-candle strategic leg behavior: candle polarity cannot create a new impulse/correction by itself.
- Dynamic endpoint extension without moving the strategic origin.
- Sub-38.2% pullbacks remain internal and do not reset strategic structure.
- >=38.2% pullbacks become strategic correction candidates.
- Close beyond the protected/control pivot produces REVERSAL_CANDIDATE, not instant opposite trend.
- Audit reason codes and state versioning.

Still intentionally pending before production use:
- Historical bootstrap/discovery of initial validated H4 structure from raw bars.
- Full strategic correction continuation/turn validation regression suite across real symbols.
- False-break and gap/session edge cases.
- Durable database state store and recovery.
- Broker-feed normalization.

The engine is suitable for architecture/regression development, not live execution yet.
