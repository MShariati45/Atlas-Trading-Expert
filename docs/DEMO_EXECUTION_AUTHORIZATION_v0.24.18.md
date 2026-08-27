# Atlas v0.24.18 — Demo Execution Authorization

This release adds a deterministic, zero-AI/API, fail-closed authorization layer before MT5 demo mutations.

## Required gates
- Account must be positively identifiable as DEMO from configured account/broker or MT5 preflight server metadata.
- `runtime/demo_preflight_report.json` must report `ready_for_paper_supervision=true`.
- H4 human approval must exist and agree with LONG/SHORT direction.
- Risk per trade <= 0.5%.
- Maximum two trades/day, one trade/symbol/day, maximum 1.0% daily risk.
- No existing position in the same symbol.
- Entry/SL/TP geometry must be valid.
- Demo execution requires two explicit local switches: environment `ATLAS_DEMO_EXECUTION=YES` and local enable file with `{"mode":"DEMO_ONLY","enabled":true}`.

LIVE or unverified accounts are forbidden. The release remains locked by default; no enable file is shipped.
