# Atlas v2 P1 — Owner Strategy + Shadow

Owner: Ali Shariati
Status: ACTIVE

P1 turns the closed P0 evidence/replay foundation into a runnable no-order Shadow system. P1 may read market data and produce real forward candidates/decisions, but it has no broker order authority.

## P1 steps

1. Freeze Owner Track A strategy spec v1.
2. Review/wrap the legacy M15 specialist detectors behind Atlas v2 interfaces.
3. Add the production outcome resolver for replay/shadow analysis.
4. Run active strategy arms: Owner Track A + C0 control; optional indicator Track B remains research-only.
5. Add reported portfolio scenario: max 2 new trades/day and 1% planned daily risk simulation.
6. Add MT5 read-only forward feed + forward calendar capture + same capture/evaluation loop as replay.
7. Freeze forward-captured observations and prove forward/replay semantic parity.
8. Add the minimal private dashboard for candidates, reasons, freshness, errors, labels, and kill/stop controls.

## P1 -> P2 gate

P2 remains closed until:
- forward/replay parity is clean over an owner-chosen span;
- no unexplained IDENTITY_CONFLICT/failure remains;
- operational H4 labels are in use;
- strategy version is frozen;
- kill/stop control is tested.

No profitability threshold is required for Demo. P2 exists to test execution.
