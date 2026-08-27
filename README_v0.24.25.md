# Atlas v0.24.25 - Controlled DEMO_ONLY Execution Gate

This checkpoint adds the final deterministic authorization/ticket layer before any demo order may be transmitted.

Key properties:
- hard rejection of LIVE/REAL/unverified servers;
- per-account execution lifecycle must already be EXECUTION_ENABLED;
- existing v0.24.18 demo authorizer still enforces human H4 approval, 0.5% risk, daily limits, one symbol trade/day, open-position lock, and explicit local demo unlock;
- official news guard must be clear;
- v0.24.24 adaptive spread guard must report NORMAL (ELEVATED is observation-only during initial forward demo);
- structural stop remains authoritative; spread can block but cannot widen the stop;
- broker contract minimum stop/volume checks;
- lot size is derived from account equity, 0.5% risk, structural stop distance, tick size/value and broker volume step;
- local idempotency ledger claims signal/account pairs before transport to prevent duplicate sends;
- post-fill verification records slippage, effective risk, fill volume and whether broker SL/TP match the authorized protection;
- zero AI/API calls in the execution path;
- no execution-enable file is shipped by default and real-money execution remains out of scope.

## Initial demo policy
Only `NORMAL` spread is executable. `ELEVATED`, `BLOCK`, or `UNAVAILABLE` spread states cannot send a demo order. This can be revisited only after forward-demo evidence.
