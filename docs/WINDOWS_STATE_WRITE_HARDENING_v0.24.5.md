# Atlas v0.24.5 - Windows State Write Hardening

Scope: persistence reliability only. No strategy, pattern, risk, execution, news, Fibonacci, H4/H1, or M15 decision logic changed.

## Incident addressed
Windows `PermissionError: [WinError 5] Access is denied` during replacement of `runtime/atlas_m15_first_state.json` caused the Shadow Paper Supervisor to exit.

## Change
`JsonFileStateStore._write()` now:
- uses a writer-specific temporary filename instead of one shared `.tmp` name;
- preserves atomic `os.replace()` semantics;
- retries transient `PermissionError` with bounded backoff (up to 6 attempts / 3.15 seconds total delay);
- cleans writer-specific temporary debris after success or final failure.

The existing runtime state file remains authoritative. No migration or deletion is required.

## Verification
Full suite: 221/221 passed, including 2 new state-store regression tests for transient Windows replacement denial and temp-file cleanup.
