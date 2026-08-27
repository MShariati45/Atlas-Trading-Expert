# Atlas v0.24.2 - News family coverage audit

## Defect found in v0.24.1
The generated calendar could report `FULL_PRIMARY_BACKBONE` when all configured official websites were reachable even if a parser failed to place a required high-impact event family into the final calendar. The observed case was CAD: Bank of Canada policy events were present, but Statistics Canada CPI/Labour Force events were absent.

## v0.24.2 correction
Readiness now requires both source health and event-family presence in the active horizon.

Required families:
- USD: FOMC, Employment Situation, CPI.
- EUR: ECB monetary-policy decisions.
- CAD: Bank of Canada rate decisions, Canada CPI, Canada Labour Force Survey.
- JPY: Bank of Japan policy decisions, Japan CPI, Japan Labour Force Survey.

Statistics Canada CPI/LFS dates for the remainder of 2026 are maintained from Statistics Canada's official 2026-2027 major economic release schedule, while the live Statistics Canada site is still checked for source health. The brittle rolling-page parser remains diagnostic only and no longer determines whether the required CAD macro families exist.

The system remains fail-closed: source failure or missing required family prevents FULL readiness.

## v0.24.3 runtime enforcement
The shadow Paper Supervisor requires the official news provider to re-check all required event families on every read. A later degraded refresh therefore forces NEWS_DATA_UNAVAILABLE / WAIT without restarting Atlas.


## v0.24.4 note
News family coverage rules are unchanged from v0.24.3; v0.24.4 adds the paper-only broker-cost gate.
