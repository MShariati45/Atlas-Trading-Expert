# Atlas v0.25.0-rc10 — GitHub Handoff

**Date:** 2026-09-01  
**Status:** FROZEN FOR CONTINUATION TOMORROW  
**Release:** `0.25.0-rc10`  
**Environment:** Windows VPS + MetaTrader 5 Demo  
**Real-money trading:** FORBIDDEN

## 1. Current Objective

RC10 is the current operational Demo release. The strategy is frozen. The current work is no longer strategy redesign; it is deployment/routing verification and forward Demo operation.

## 2. Strategy Authority — Frozen

Authoritative flow:

1. M15 specialist agents scan the active watchlist for approved patterns.
2. When a specialist finds a clean candidate, the Coordinator receives the candidate.
3. H4 direction is mandatory. The pattern must align with the owner-validated H4 impulse direction.
4. H1 is context only and must not become a universal hard gate.
5. Fibonacci is not an M15 entry gate. Its retained strategic role is H4 correction-depth / major-pivot-candidate measurement at 38.2%.
6. Static-zone validation checks meaningful nearby D1/H4 zones and requires enough room for the strategy target, including the 2R clean-room rule.
7. Live-news guard must be fresh and must block affected symbols around major events.
8. Trading-session/day rules apply.
9. Coordinator sends a fully qualified package to Supervisor.
10. Supervisor is final trade authority.
11. Execution is isolated per MT5 account.
12. Laboratory uses the same analysis logic but must never execute trades.

## 3. H4 Manual Validation — Mandatory

Owner validation of the current H4 impulse remains part of the system for both Watchlist and Laboratory.

Required fields:
- Direction
- Impulse start
- Impulse end
- Owner confirmation / correction

The validation remains effective while price stays inside the approved impulse boundaries. A boundary break requires revalidation. Owner corrections are training evidence and must remain authoritative for the current decision state.

## 4. Demo vs Live Risk

### Demo
- `risk_per_trade_pct`: 0.5%
- Demo may take unlimited qualified trades for forward-data collection.
- Real-money is forbidden.

### Future Live
- Maximum 2 trade slots per day.
- Maximum 1% daily risk.
- Default 0.5% risk per trade unless account-specific profile overrides it.
- Existing open positions reduce available new-trade capacity according to the live risk policy.

## 5. Multi-Account Architecture

Atlas is designed for multiple MT5 accounts.

Each account profile owns:
- account id
- terminal instance id
- terminal executable path
- allowed symbols
- symbol mapping
- risk per trade
- maximum daily risk
- trade/concurrency limits
- enabled / emergency-stop state

Current Demo profile:
- Account: `ATLAS-DEMO`
- Terminal instance: `PRIMARY_DEMO`
- Terminal: `C:\Program Files\MetaTrader 5\terminal64.exe`
- Symbols: EURUSD, USDCAD, USDJPY, XAUUSD
- Risk/trade: 0.5%
- Max daily risk: 1.0%
- Demo unlimited qualified trades: enabled

## 6. RC10 Operational Improvements

RC10 operational startup is controlled through `atlasctl.py`.

Primary commands:

```powershell
C:\Atlas\.venv\Scripts\python.exe .\atlasctl.py launch-demo
C:\Atlas\.venv\Scripts\python.exe .\atlasctl.py diagnose
C:\Atlas\.venv\Scripts\python.exe .\atlasctl.py status
C:\Atlas\.venv\Scripts\python.exe .\atlasctl.py stop-demo
C:\Atlas\.venv\Scripts\python.exe .\atlasctl.py restart-demo
```

The launcher automatically composes:
- Demo account profile / MT5 path
- official news refresh
- adaptive spread baseline
- fresh MT5 Demo readiness report
- supervised Demo preflight
- Demo execution control
- service manager
- Web/API
- Supervisor runtime
- isolated account workers
- heartbeats and diagnostic evidence

If launch fails, execution must return to PAUSED/fail-closed state.

## 7. Verified Today

Verified successfully:
- MT5 Demo terminal connectivity
- Fresh M15 market data
- Four-symbol watchlist
- News refresh: 76 events across USD/EUR/CAD/JPY required families
- Adaptive spread baseline automatically created in RC9/RC10 launch path
- Account profile terminal path configured
- Account worker initialized and wrote runtime databases
- Supervisor heartbeat active
- Web/API heartbeat active
- RC10 service stack launched
- Web/API responds on `127.0.0.1:8080` but rejects direct local routes with 404 under current proxy/host policy

Important current observation:
- `http://127.0.0.1:8080/` and `/app/login` return HTTP 404, not connection refusal.
- This proves the Web/API process is alive.
- The remaining issue is public reverse-proxy / host routing so `app.atlastradingexpert.com` exposes the RC10 cockpit instead of the previous frontend.

## 8. Current Stop Point

**Do not redesign strategy.**  
**Do not perform more internal file searches unless `atlasctl diagnose` cannot identify a failure.**

Next session begins at reverse-proxy/public-route verification.

First command tomorrow:

```powershell
Get-Process caddy -ErrorAction SilentlyContinue | Select-Object Id,Path,StartTime
```

Then verify/reload Caddy so:

`https://app.atlastradingexpert.com/...` -> RC10 Web/API on `127.0.0.1:8080`

After routing is correct:
1. Sign into Owner cockpit.
2. Verify real RC10 status widgets/heartbeats.
3. Verify H4 manual validation UI on Watchlist + Laboratory.
4. Verify live chart/detail pages.
5. Leave Atlas running for forward Demo trading.
6. Use `atlasctl diagnose` for any blocked/failed state.

## 9. Troubleshooting Standard

Target incident response: 10–15 minutes.

Order of operations:
1. `atlasctl status`
2. `atlasctl diagnose`
3. Review exact component reason / recent logs from diagnostic output
4. Restart only the failed component or use `restart-demo`
5. Do not manually inspect scattered legacy scripts as the normal workflow

Desired cockpit states:
- RUNNING
- WAITING
- LEARNING
- BLOCKED
- FAILED

Every BLOCKED/FAILED state must expose a human-readable reason and last successful heartbeat.

## 10. Frontend / Cockpit Requirements — Frozen Direction

Owner cockpit should surface actual backend truth, not decorative placeholders:
- M15 specialist activity / detected pattern
- Coordinator state
- H4 owner-validation state
- nearest D1/H4 static zone
- news state
- spread guard state
- Supervisor state
- MT5 worker state
- active Demo positions
- risk/account information
- trade decision/rejection reasons
- real heartbeat indicators
- Watchlist pair detail with live MT5 chart, detected pattern overlay, and nearest relevant static zone

The frontend must remain extensible for future reporting and analytics without adding architectural noise.

## 11. Lead Center and Internal Messaging

Required product capabilities retained for future frontend completion:
- Public demo-request form -> Lead Center only
- Lead fields: first name, last name, phone, email, short message
- Owner <-> trader internal text messaging inside Atlas
- Trader-facing portal is simpler than Owner cockpit and limited to assigned account information and financial reporting

## 12. Research / Knowledge Supervision

Supervisor may monitor reliable professional publications / technical-analysis sources and propose domain-specific learning updates to specialist agents.

Owner must be shown:
- source/reference
- reliability assessment
- summary
- affected specialist(s)
- what instruction/update was proposed/applied

No silent knowledge modification.

## 13. API / Cost Discipline

- Market history already persisted must not be repeatedly re-downloaded.
- Prefer event-driven / incremental processing.
- Avoid unnecessary AI/API calls.
- News refresh path currently operates with zero AI calls.
- Historical data and derived state should be reused.

## 14. Release Quality

RC10 was produced as an operational correction to RC9 startup sequencing.

Last reported verification before VPS launch:
- 419 tests passed
- 0 failed
- Code quality audit PASS
- Fresh deployment compile PASS
- Fresh external-review extraction test PASS

## 15. Do Not Delete Yet

Keep current RC10 release and runtime evidence until public routing + owner cockpit + forward Demo execution are verified.

After RC10 is proven stable, clean obsolete VPS release folders and legacy artifacts deliberately, preserving only documented backup/audit material.
