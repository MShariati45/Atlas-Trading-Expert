# Atlas v0.15 - Live M15 Specialist Runtime

Status: read-only / paper observation. No order-send path is enabled.

- Completed MT5 M15 candles feed all six specialist state machines.
- M15 state is persisted in the same JSON state store as H4/H1.
- Confirmed local swings provide deterministic candidate discovery inputs for Multiple Top/Bottom and conservative geometry proposals for H&S, Channel, Triangle/Wedge and Flag/Pennant.
- Fibonacci activation is enforced: Flag/Pennant early access below 38.2%; broader specialist layer at/above 38.2%.
- Current reports are normalized by M15 Coordinator on every observation poll.
- Dashboard may show PAPER_REVIEW_READY when a real M15 opportunity package is ready, but execution remains disabled.
- Pattern candidate detectors are intentionally conservative and require demo/chart validation before any execution phase.
