# Independent Review Remediation Matrix - v0.24.28

## Source reviews
Two independent reviews were compared against the actual v0.24.27 source. The accepted findings below were reproduced or confirmed in source before remediation.

| Finding | Review consensus | v0.24.28 action |
|---|---|---|
| Gate and transport used disconnected idempotency defaults | Both reviewers | One SQLite ledger; canonical runtime injects it everywhere |
| JSON check/read/write race and duplicate claim exception | Both reviewers | JSON runtime ledger removed; atomic SQLite claim; duplicate returns blocked decision |
| Daily risk/trade counters defaulted to zero and were caller-supplied | Claude | MT5AccountRiskStateService derives authoritative state from ledger + current MT5 positions |
| Final gate could use fail-open NewsGuard | Claude | Final gate requires LiveNewsGuardService; unavailable provider blocks |
| H4 approval never expired | Both reviewers | 24h TTL default + optional structure-token revalidation |
| modify_stop / close_position bypassed safety chain | Grok | Legacy mutation methods disabled; dedicated supervised management remains required |
| Crash window after broker send | Grok | SEND_ATTEMPTED pre-send, SEND_ACKED immediately after acceptance, restart reconciliation |
| Risk math assumed uniform tick economics | Grok | MT5BrokerContractService uses order_calc_profit account-currency loss per lot when available |
| DEMO identity strongest only at transport | Grok | Account enablement now records authoritative MT5 identity; transport rechecks immediately pre-send |
| Audit durability/integrity weak | Grok | Hash-chain + redaction + flush/fsync |
| Package version mismatch | Grok | VERSION and pyproject moved to 0.24.28 |
| Claimed fill-volume AttributeError | Grok | Not present in inspected v0.24.27 copy; exact edge-path regression test added and passes |

## Safety posture
v0.24.28 is a staging/demo checkpoint. New-order execution remains DEMO-only and fail-closed. REAL/LIVE is not authorized. Automated stop modification/close management is intentionally unavailable until the supervised-management boundary is implemented and tested.
