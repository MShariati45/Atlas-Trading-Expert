# ATLAS RC17 — Full Engineering Handoff and Audit Report

**Date:** September 22, 2026  
**Project:** Atlas Trading Expert  
**Active release:** `Atlas-0.25.0-rc17-FINAL`  
**Primary VPS root:** `C:\Atlas2\Atlas-0.25.0-rc17-FINAL`  
**Primary objective:** Prove reliable end-to-end demo trade execution for Strategy #1 while preserving fail-closed safety and keeping live/real-money trading disabled.

---

## 1. Executive Summary

Atlas has progressed through multiple release candidates and now has a substantial operational framework: service manager, supervised runtime, account workers, execution control, health checks, doctor/diagnostics, recovery logic, authorization chains, and a real MT5 demo execution transport.

However, the project has not yet achieved its central practical objective: **repeatable Strategy #1 trade execution on the ATLAS-DEMO MT5 account**.

The most important finding as of September 22, 2026 is that the current controlled Demo launch is not blocked by Strategy #1, MT5 credentials, account-worker registration, recovery blockers, or health checks. Instead, the launch is being blocked by a **Windows runtime process-lifecycle / listener-ownership defect**.

The latest evidence proves that multiple stale RC17 web processes remain bound to `127.0.0.1:8080` after earlier launches. A new, valid RC17 web listener is created and correctly verified against the current service manager, but Atlas still sees the stale listeners and therefore fails closed with `WEB_LISTENER_IDENTITY_NOT_VERIFIED`.

This is now the leading backend defect that must be addressed before trade execution can be tested properly.

A fresh Codex session should therefore begin with a **full backend audit**, not another isolated patch. Codex should act as a senior auditor/release engineer, map the runtime architecture, verify process lifecycle ownership and cleanup, verify Doctor coverage, and then trace Strategy #1 end-to-end from signal generation to MT5 `order_send()`.

---

## 2. Original Purpose of Atlas

The purpose of Atlas has always been practical:

1. Collect market information.
2. Apply Strategy #1 rules.
3. Identify legitimate trade candidates.
4. Pass candidates through safety and authorization gates.
5. Execute trades on a **Demo MT5 account**.
6. Collect real execution/performance data.
7. Use that data to determine whether the strategy is worth further development.

The Demo account is specifically intended for research and validation. Profitability is not the first objective at this stage; **proof of reliable execution and data collection is**.

Atlas should therefore be judged first on whether it can safely and repeatably:

`market data -> strategy decision -> authorization -> account dispatch -> MT5 order check -> MT5 order send -> reconciliation -> reporting`

without requiring repeated manual debugging.

---

## 3. Release History and Current Scope

### RC15

RC15 was running on the VPS and produced live operational observations. A major issue was that many Strategy #1 patterns were blocked by a static-zone agent.

### RC16

RC16 became the release-certified baseline and was deployed successfully. It remains a protected historical baseline and must not be modified during RC17 work.

### RC17

RC17 added or expanded:

- new landing/login experience;
- Owner Dashboard;
- Watchlist;
- Symbol Detail;
- Laboratory;
- News;
- operational CLI (`atlasctl.py`);
- Doctor and diagnosis flows;
- controlled Demo launch/stop/restart;
- execution-control state management;
- supervised runtime;
- account-worker management;
- recovery checks;
- launch readiness checks;
- process ownership checks;
- stricter Windows fail-closed behavior.

RC17 remains the active development target.

---

## 4. Strategy Separation

### Strategy #1

Strategy #1 is the primary trading strategy whose execution is being validated.

It must **not be modified simply to force more trades**.

The objective is to prove that when a legitimate Strategy #1 candidate passes all required gates, Atlas can execute it on ATLAS-DEMO.

### SuperTrend

SuperTrend is a second strategy under research.

It remains:

- research-only;
- separate from Strategy #1;
- non-executing;
- not permitted to call `order_check()`;
- not permitted to call `order_send()`;
- not a global blocker for Strategy #1;
- configured as non-required.

The earlier message:

`Research observations recorded; execution prohibited.`

was confirmed to belong to SuperTrend research only and is not the reason Strategy #1 is not trading.

---

## 5. Confirmed Real Strategy #1 Execution Path

Codex previously confirmed that Strategy #1 reaches a real MT5 Demo execution path:

```text
Strategy #1
  -> Coordinator
  -> Supervisor
  -> News / session / freshness checks
  -> Account dispatch
  -> ATLAS-DEMO account worker
  -> DemoExecutionAuthorizer
  -> DemoExecutionRuntime
  -> DemoExecutionTransport
  -> MetaTrader5.order_check()
  -> MetaTrader5.order_send()
```

This is not paper execution.

When all gates pass, Atlas is designed to reach the real MT5 Demo terminal.

---

## 6. Previously Healthy Operational State

Before the latest diagnostic deployment/restart work, Atlas Doctor reported:

```text
SYSTEM: OK
PRIMARY ROOT CAUSE: NONE
IMPACT: No blocking or degraded operational condition was found.
REAL MONEY: DISABLED
```

Demo execution control was confirmed armed:

```text
state: DEMO_ENABLED
changed_by: OWNER_LAUNCHER
reason: RC9 controlled Demo operational launch
```

The authorized chain was confirmed running:

```text
run_atlas_service_manager.py --allow-demo-execution --port 8080
  -> run_supervised_demo_runtime.py --allow-execution
  -> run_account_worker_manager.py --allow-demo-execution
  -> run_mt5_account_worker.py --account-id ATLAS-DEMO --allow-execution
```

This proved that the authorization chain itself could be established.

---

## 7. Original MT5 Execution Failure

The investigation eventually reached the real MT5 transport.

The critical failure was:

```text
mt5.order_check(request) returned None
```

Atlas correctly failed closed and **did not call `order_send()`**.

At that time, Atlas did not capture enough information to explain why MetaTrader 5 returned `None`.

This was the original reason a diagnostic patch was created.

---

## 8. MT5 Diagnostic Instrumentation

Codex created a narrow diagnostic change in:

`atlas/execution/demo_transport.py`

with regression coverage in:

`tests/test_rc17_mt5_order_check_none_diagnostics.py`

The change requires that when:

`mt5.order_check(request) -> None`

Atlas immediately calls:

`mt5.last_error()`

before any other MT5 API call.

Required behavior:

```text
order_check
  -> last_error
  -> persist sanitized diagnostics
  -> FAILED
```

No retry and no `order_send()` are permitted after that failure.

Diagnostics now include, where available:

- timestamp;
- account ID;
- canonical symbol;
- broker symbol;
- direction;
- numeric order type;
- sanitized MT5 request;
- `mt5.last_error()`;
- terminal connection/trading state;
- account trading/expert state;
- verified Demo identity;
- symbol visibility/trade mode;
- order/execution/filling modes;
- digits, point, tick size;
- volume min/max/step;
- stops/freeze levels;
- bid/ask.

Secrets and credentials are excluded.

Validation reported:

- focused tests: 9 passed;
- relevant execution/security suite: 53 passed;
- compilation: PASS;
- package verification: PASS;
- rollback verification: PASS;
- idempotent redeployment simulation: PASS.

The diagnostic package was successfully deployed to RC17.

---

## 9. Important Change in the Investigation

After the MT5 diagnostic patch was deployed, Atlas needed to be restarted so the new code could be loaded.

This exposed a separate problem in the controlled Demo runtime startup/cleanup architecture.

The current blocker therefore shifted from:

`Why did mt5.order_check() return None?`

to:

`Why can the RC17 controlled Demo runtime no longer reach a clean RUNNING state after restart?`

The MT5 diagnostic code itself has not been shown to cause the launch failure.

---

## 10. Windows Manual-Start Ownership Problem

A manual restart using `Start-Process python` created a Windows launcher/interpreter topology with an additional native console host.

Atlas initially interpreted Windows `conhost.exe` as an unexpected Atlas descendant and reported:

```text
PROCESS_OWNERSHIP_AMBIGUOUS
UNEXPECTED_OR_AMBIGUOUS_DESCENDANT
```

This was a genuine Windows process-classification defect.

A correction was created so narrowly validated native Windows `conhost.exe` infrastructure could be ignored as OS infrastructure while unrelated descendants still fail closed.

This problem was real, but it was not the final launch blocker.

---

## 11. Controlled Launch Failure: Web Listener Identity

Using the official RC17 launcher, Atlas repeatedly failed at:

```text
FailureStage: WAIT_RUNTIME_READY
FailureCategory: WEB_LISTENER_IDENTITY_NOT_VERIFIED
Exception: RUNTIME_READINESS_TIMEOUT: WEB_LISTENER_IDENTITY_NOT_VERIFIED
```

Important evidence showed:

- service manager started;
- manager remained alive during readiness;
- account worker registered;
- recovery blockers were empty;
- health endpoint responded;
- listener was seen during startup;
- listener query itself did not fail;
- launch timed out only because the listener ownership proof did not pass.

---

## 12. V1 Windows Listener Identity Fix

V1 attempted to support the real Windows launcher/interpreter hierarchy.

It recognized that a `.venv` or Windows launcher can delegate execution to a separate `pythoncore-3.12-64\python.exe`, which may own the TCP socket.

V1 added ancestry-aware verification and preserved fail-closed security.

The package passed local and VPS validation but the real launch still failed.

Reason: V1 still required exactly one listener PID on numeric port 8080.

---

## 13. V2 Windows Runtime Identity Fix

V2 attempted to improve endpoint scoping and diagnostics.

Package:

`RC17-FINAL-windows-runtime-identity-v2.zip`

SHA-256:

`28AC6D7FDF926C3B7785E08912FC985C707ED1A0E1A991A38F90531633AFA292`

Deployment on VPS succeeded:

```text
PACKAGE_VERIFICATION: PASS
APPLICATION_FILES: 1
VALIDATION_FILES: 1
8 passed
DEPLOYMENT: PASS
SERVICE_RESTART: NOT_PERFORMED
EXECUTION_CONTROL: UNCHANGED
LIVE_TRADING: DISABLED
REAL_MONEY: DISABLED
```

However, the official launch still failed at the same readiness category.

---

## 14. Most Important Current Evidence

The latest evidence file is:

`windows-runtime-identity-v3-evidence.json`

It proves the deployed module is:

`C:\Atlas2\Atlas-0.25.0-rc17-FINAL\atlas\operations\demo_launcher.py`

and records three listener PIDs considered for `127.0.0.1:8080`:

```text
1872
5484
7560
```

The first failed aggregate predicate is:

`listener_count_valid`

Exactly one process is fully qualified as the current RC17 listener:

```text
PID 7560
parent PID 6424
manager ancestry verified = true
process chain complete = true
```

Its command is:

```text
run_secure_staging_web.py --host 127.0.0.1 --port 8080
```

The current manager chain is also fully validated.

---

## 15. Critical New Finding: Two Stale RC17 Web Listeners

The latest evidence finally reveals why listener count remains invalid.

Two additional processes are still bound to the same loopback endpoint:

```text
PID 1872
PID 5484
```

Both are real Python processes running the exact RC17 web script:

```text
C:\Atlas2\Atlas-0.25.0-rc17-FINAL\run_secure_staging_web.py
--host 127.0.0.1
--port 8080
```

Their current parent PIDs are:

```text
1872 -> parent 8976
5484 -> parent 9188
```

However, neither reaches the **current** manager ancestry, so Atlas correctly marks:

```text
manager_ancestry_verified = false
process_chain_complete = false
```

for both.

The new current listener PID 7560 is valid and belongs to the current launch chain.

After the failed launch cleanup, PID 7560 is gone, while PIDs 1872 and 5484 remain listening on:

```text
127.0.0.1:8080
```

This is the strongest evidence so far that the primary backend issue is a **process lifecycle / stale child cleanup defect** rather than an endpoint-matching defect.

In other words, older RC17 web processes appear to survive previous manager shutdown/restart cycles and continue holding the loopback web port.

This causes every new controlled launch to observe multiple legitimate-looking RC17 web servers on the same endpoint, which correctly triggers fail-closed readiness.

---

## 16. Current Leading Root-Cause Hypothesis

The evidence strongly indicates that RC17's process ownership and cleanup model is incomplete.

Likely defect class:

**Old `run_secure_staging_web.py` child/interpreter processes are not reliably terminated or reclaimed when their owning service-manager chain exits or is replaced.**

This produces stale/orphaned Atlas web listeners that remain alive across launch attempts.

The current launch then creates a new web process correctly, but readiness sees:

- stale RC17 listener A;
- stale RC17 listener B;
- new current RC17 listener C.

Because multiple processes can serve `127.0.0.1:8080`, Atlas fails closed.

This behavior also explains why V1 and V2 listener-identity patches could not solve the issue: they were improving listener classification while the deeper lifecycle defect continued creating stale listeners.

This must now be proven by a fresh source audit.

---

## 17. Why Doctor Has Not Been Sufficient

A major project concern is that substantial effort was spent building Doctor/diagnostic tooling, yet the actual operational defect remained difficult to identify.

Doctor correctly detects aggregate failure conditions such as:

- process ownership ambiguity;
- runtime readiness failure;
- listener identity not verified.

But it did not initially explain the causal lifecycle defect:

- which listeners are stale;
- which previous manager each belongs to;
- why they survived cleanup;
- whether their parent is alive;
- whether they are orphaned;
- whether Atlas should safely terminate them;
- which cleanup stage failed to remove them.

Doctor should eventually be upgraded to diagnose this automatically.

A useful Doctor result should say something like:

```text
SYSTEM: ERROR
PRIMARY ROOT CAUSE: STALE_MANAGED_WEB_LISTENERS
CURRENT MANAGER: <pid>
CURRENT VALID WEB LISTENER: <pid>
STALE RC17 WEB LISTENERS: <pid list>
STALE PARENT MANAGERS: <pid list>
PORT: 127.0.0.1:8080
SAFE NEXT ACTION: controlled stale-owned-process cleanup / recovery
```

rather than stopping at the generic listener-identity category.

---

## 18. Backend Areas That Need a Fresh Audit

The next Codex session should audit the backend systematically instead of patching one symptom at a time.

### A. Process lifecycle

Audit every long-running Atlas process:

- service-manager launcher;
- service-manager interpreter;
- supervised runtime;
- account-worker manager;
- account workers;
- secure staging web launcher;
- secure staging web interpreter;
- research processes;
- console helpers where relevant.

For each process determine:

- who starts it;
- who owns it;
- how ownership is persisted;
- how parent/child ancestry is verified;
- how graceful shutdown works;
- how forced cleanup works;
- what happens if the parent exits first;
- what happens if the launcher exits but delegated interpreter remains;
- how stale processes are detected after a crash/restart;
- how Atlas distinguishes safe-to-clean owned processes from unrelated processes.

### B. Port/listener lifecycle

Audit:

- exact binding model for port 8080;
- whether `SO_REUSEADDR` or Windows socket reuse is involved;
- how multiple RC17 processes can bind the same endpoint;
- how old web processes survive;
- why cleanup does not reclaim them;
- whether pre-launch should reject/clean stale Atlas-owned listeners before creating a new web server.

### C. PID/lock/ownership records

Audit:

- PID files;
- lock files;
- ownership records;
- heartbeat state;
- manager replacement logic;
- stale-state cleanup;
- recovery state after abnormal shutdown.

### D. Controlled launch/stop/restart

Audit:

- `launch-demo`;
- `stop-demo`;
- `restart-demo`;
- failure cleanup;
- idempotence;
- crash recovery;
- partial startup rollback.

A stopped/restarted Atlas stack should not leave a web listener behind.

### E. Doctor / Diagnose

Doctor must be evaluated as a product feature, not merely a set of tests.

It should detect and explain:

- stale owned processes;
- stale listeners;
- mismatched PID/lock state;
- orphaned delegated interpreters;
- missing worker registrations;
- broken authorization chains;
- occupied ports;
- recovery blockers;
- MT5 transport failures;
- exact `order_check()` failure reason.

### F. Trade execution path

After runtime lifecycle is repaired, audit the complete Strategy #1 execution path from a legitimate signal to MT5.

No subsystem should be assumed healthy merely because unit tests pass.

---

## 19. Required End-to-End Trade Audit

Once the controlled Demo stack reaches `RUNNING`, trace one Strategy #1 candidate through every stage:

1. market data ingestion;
2. Strategy #1 signal generation;
3. candidate persistence/journal;
4. coordinator acceptance;
5. supervisor gates;
6. News Guard;
7. session check;
8. market-data freshness;
9. timestamp validation;
10. spread protection;
11. risk rules;
12. account selection;
13. Demo authorization;
14. account dispatch;
15. worker receipt;
16. symbol mapping;
17. volume normalization;
18. SL/TP validation;
19. filling mode selection;
20. request construction;
21. `mt5.order_check()`;
22. `mt5.last_error()` if needed;
23. `mt5.order_send()`;
24. fill/rejection persistence;
25. position reconciliation;
26. dashboard/reporting update.

The audit must identify the first actual blocker with concrete evidence.

---

## 20. Demo-Only Execution Acceptance Philosophy

The project's purpose is to validate execution and collect research data on a Demo account.

Therefore two separate acceptance proofs should exist:

### Infrastructure execution proof

Atlas should have a tightly controlled, Demo-only transport acceptance mechanism proving that the authorized Demo account can receive an order through the real transport path.

This must be clearly separated from Strategy #1 and must never be available for Live/Real Money.

It should not silently bypass authorization or risk controls.

### Strategy execution proof

Separately, Atlas must prove that a **legitimate Strategy #1 candidate** can traverse the normal strategy path and reach the same transport.

Do not alter Strategy #1 rules just to create a signal.

These two proofs prevent confusion between:

- infrastructure cannot trade;
- strategy has not generated a qualifying candidate.

---

## 21. Current Safety State

As of the latest failed launch:

- Strategy #1: unchanged;
- SuperTrend: research-only;
- Demo execution: PAUSED / disabled after failure;
- Live trading: disabled;
- Real Money: disabled;
- Emergency stop: false;
- RC16: untouched;
- current failed manager chain: cleaned up;
- stale web listeners: still present according to latest evidence.

---

## 22. Recommended Next Development Approach

Start a completely fresh Codex session.

Do not begin by asking Codex to patch `listener_count_valid`.

Instead, instruct Codex to act as an independent backend auditor and release engineer.

The first deliverable should be an architecture and defect audit.

Only after Codex proves the lifecycle defect should it implement a correction.

The correction should fix the root process-lifecycle problem, update Doctor, add regression tests based on the actual VPS topology, and then allow one controlled Demo acceptance launch.

Once `RUNNING`, return to the original MT5 objective and wait for / observe the next legitimate Strategy #1 execution attempt with the previously deployed `order_check(None)` diagnostics active.

---

# Fresh Codex Audit Prompt

## ATLAS RC17 — FULL BACKEND AUDIT, RUNTIME REPAIR, AND DEMO EXECUTION READINESS

Act as the **independent senior backend auditor, Windows runtime engineer, trading-system release engineer, and safety reviewer** for Atlas RC17.

This is a fresh audit. Do not inherit assumptions from previous patch attempts. Treat the repository and the supplied runtime evidence as authoritative.

### Primary business objective

Atlas exists to collect market information, apply Strategy #1, execute legitimate trades on the ATLAS-DEMO MT5 account, and collect execution/performance data so the strategy can be evaluated.

The current system has been under development for more than two months and still has not demonstrated reliable end-to-end Demo trade execution.

Your priority is therefore:

1. audit the backend architecture;
2. find structural defects preventing reliable controlled Demo operation;
3. fix those defects safely;
4. make Doctor/diagnose capable of identifying future failures clearly;
5. prove the Demo runtime can reach a healthy `RUNNING` state;
6. then trace Strategy #1 end-to-end to actual MT5 execution.

Do not spend this session on frontend cosmetics.

### Target

```text
C:\Atlas2\Atlas-0.25.0-rc17-FINAL
```

RC16 is a protected historical baseline and must remain untouched.

### Non-negotiable safety

- Live trading must remain disabled.
- Real Money must remain disabled.
- SuperTrend remains research-only.
- Do not weaken News Guard, risk, spread, broker, timestamp, freshness, authorization, reconciliation, or ownership controls.
- Do not change Strategy #1 simply to create more trades.
- Do not submit a Live order.
- Do not modify account credentials or secrets.
- Fail closed when ownership or authorization is genuinely uncertain.

### Current most important runtime evidence

The deployed V2 module is:

```text
C:\Atlas2\Atlas-0.25.0-rc17-FINAL\atlas\operations\demo_launcher.py
```

The controlled launch fails at:

```text
WAIT_RUNTIME_READY
WEB_LISTENER_IDENTITY_NOT_VERIFIED
```

Current listener evidence showed three PIDs:

```text
1872
5484
7560
```

The current launch's valid web listener was PID 7560 with process chain:

```text
current service manager
  -> current web .venv launcher PID 6424
  -> current pythoncore socket owner PID 7560
```

PID 7560:

```text
run_secure_staging_web.py --host 127.0.0.1 --port 8080
manager_ancestry_verified = true
process_chain_complete = true
```

But two other listeners remained:

```text
PID 1872 -> parent PID 8976
PID 5484 -> parent PID 9188
```

Both are also running:

```text
C:\Atlas2\Atlas-0.25.0-rc17-FINAL\run_secure_staging_web.py
--host 127.0.0.1
--port 8080
```

Both fail only current-manager ancestry verification.

After failed launch cleanup, current PID 7560 was gone, while `netstat` still showed:

```text
TCP 127.0.0.1:8080 LISTENING 1872
TCP 127.0.0.1:8080 LISTENING 5484
```

This strongly indicates stale/orphaned RC17 web-server processes from earlier service-manager generations.

### FIRST TASK — full process lifecycle audit

Before changing code, map every persistent Atlas process and its owner.

Audit:

- `atlasctl.py`;
- `atlas.operations.demo_launcher`;
- `run_atlas_service_manager.py`;
- `run_supervised_demo_runtime.py`;
- `run_account_worker_manager.py`;
- `run_mt5_account_worker.py`;
- `run_secure_staging_web.py`;
- all process creation helpers;
- all process cleanup/termination helpers;
- PID files;
- lock files;
- heartbeat state;
- ownership discovery;
- orphan recovery;
- service replacement;
- Windows launcher/interpreter delegation.

For every long-running process document:

```text
creator
launcher PID
real interpreter PID
parent relationship
ownership evidence
shutdown signal
forced cleanup path
crash recovery behavior
stale-process detection
```

### SECOND TASK — prove why PIDs 1872 and 5484 survived

Determine exactly:

1. which historical launch created PID 1872;
2. which historical launch created PID 5484;
3. whether parent PIDs 8976 and 9188 are alive or dead;
4. why the web child survived the manager/restart/cleanup operation;
5. whether delegated Python interpreters are outside the cleanup tree Atlas currently terminates;
6. whether PID/lock ownership only tracks the manager and misses managed web children;
7. whether stop/restart cleanup waits for descendants and verifies endpoint release;
8. whether port 8080 reuse behavior allowed multiple stale listeners;
9. whether a crash or forced manager termination bypassed web cleanup;
10. whether stale owned web processes can be safely proven and reclaimed before launch.

Do not solve this by simply ignoring stale listeners.

Fix the lifecycle that creates them.

### THIRD TASK — controlled startup/recovery design

A correct controlled launch should guarantee this invariant before readiness succeeds:

```text
There is exactly one current, fully owned Atlas web listener capable of serving the requested endpoint,
and no stale Atlas-owned listener from an earlier manager generation remains capable of serving that endpoint.
```

Design the cleanup/recovery mechanism so that before starting a new web service Atlas can safely identify stale RC17-owned listeners using strong proof such as:

- exact RC17 root;
- exact web script;
- expected command/host/port;
- historical manager ownership evidence where available;
- current absence of legitimate owning manager;
- no ambiguity with unrelated processes.

Never terminate a process merely because it is Python or listening on 8080.

### FOURTH TASK — audit stop-demo / restart-demo / failure cleanup

Audit and test:

```text
launch-demo
stop-demo
restart-demo
startup rollback
readiness timeout cleanup
manager crash recovery
partial child startup
manual/abnormal termination recovery
```

After any successful stop or failed launch, assert that all owned managed children are gone and the managed endpoint is released.

Add explicit regression tests for delegated Windows launcher/interpreter pairs.

### FIFTH TASK — Doctor and diagnose audit

Doctor must diagnose the causal problem, not only the aggregate symptom.

For stale listeners it should report something equivalent to:

```text
PRIMARY ROOT CAUSE: STALE_MANAGED_WEB_LISTENERS
CURRENT MANAGER: ...
CURRENT VALID LISTENER: ...
STALE LISTENERS: ...
STALE PARENT MANAGERS: ...
ENDPOINT: 127.0.0.1:8080
SAFE NEXT ACTION: ...
```

Audit all Doctor rules against the real launch lifecycle.

Ensure Doctor can distinguish:

- healthy system;
- stale owned listener;
- unrelated port conflict;
- ambiguous ownership;
- missing worker;
- broken authorization chain;
- recovery blocker;
- MT5 transport error;
- execution-control pause.

### SIXTH TASK — review the entire backend for latent launch blockers

Do not stop after fixing the stale listener.

Audit the complete `launch-demo -> RUNNING` path and identify any next latent blocker that would produce another patch cycle.

Review:

- preflight;
- execution-control transition;
- manager startup;
- web startup;
- health identity;
- process identity;
- supervised runtime;
- account worker registration;
- recovery assessment;
- authorization chain;
- final RUNNING persistence.

Provide a defect table with:

```text
ID
severity
component
symptom
root cause
proof
fix required
regression test
```

### SEVENTH TASK — end-to-end Strategy #1 execution audit

After the controlled Demo stack can reliably reach RUNNING, trace a legitimate Strategy #1 candidate through the full backend:

```text
market data
-> Strategy #1
-> decision/candidate journal
-> coordinator
-> supervisor
-> News Guard
-> session gate
-> freshness/timestamp gates
-> spread gate
-> risk gate
-> account selection
-> Demo authorization
-> dispatch
-> account worker
-> broker symbol mapping
-> order request construction
-> mt5.order_check()
-> mt5.order_send()
-> persistence
-> reconciliation
```

For every stage, identify:

- input;
- output;
- blocking conditions;
- persistence evidence;
- diagnostic evidence;
- Doctor visibility.

The first blocker must be reported with exact code and runtime evidence.

### Existing MT5 diagnostic patch

A previous validated patch already instruments:

```text
mt5.order_check(request) returns None
```

by immediately recording:

```text
mt5.last_error()
```

plus sanitized request, account, symbol, terminal, filling mode, volume, stops, bid/ask, and related broker state.

Do not remove or weaken this patch.

Once Strategy #1 legitimately reaches MT5 again, use this evidence to identify the original MT5 failure if it recurs.

### Demo execution acceptance model

We need two distinct proofs:

#### 1. Infrastructure execution proof

Design or verify a strictly Demo-only acceptance path that proves Atlas can submit a controlled test order to ATLAS-DEMO through the real broker transport.

It must be impossible to use for Live/Real Money.

It must not masquerade as a Strategy #1 signal.

If such a path already exists, audit it.

If it does not exist, propose the safest minimal architecture before implementing it.

Do not execute a test order during source audit unless explicitly authorized in the acceptance phase.

#### 2. Strategy execution proof

A legitimate Strategy #1 candidate must also be shown capable of reaching the same transport without altering Strategy #1 rules.

This distinction is essential so we can tell the difference between:

```text
transport cannot trade
```

and:

```text
strategy has no qualifying signal
```

### Testing requirements

Before packaging any change, run:

- process lifecycle tests;
- Windows launcher/interpreter tests;
- stale-child recovery tests;
- listener ownership tests;
- `launch-demo` tests;
- `stop-demo` tests;
- `restart-demo` tests;
- readiness tests;
- recovery tests;
- Doctor tests;
- diagnose tests;
- authorization-chain tests;
- execution-control tests;
- relevant security tests;
- relevant Strategy #1 / dispatch tests;
- relevant Demo transport tests;
- full practical RC17 regression suite available in the repository.

Report exact totals.

No MT5 Live initialization.
No Live order.
No Real Money.

### Packaging requirement

Do not create a deployment package until the audit has identified the real lifecycle defect and all required backend corrections.

Prefer ONE consolidated RC17 backend reliability package rather than another series of symptom patches.

The package must:

- enforce the exact RC17-FINAL target;
- contain only required source/tests;
- include manifests/hashes;
- create automatic backup;
- validate before deployment;
- compile installed files;
- run focused regression tests;
- rollback exactly on failure;
- verify rollback hashes;
- support safe idempotent redeployment;
- NOT automatically launch Atlas;
- NOT change execution-control state;
- NOT enable Live;
- NOT enable Real Money.

### Required final report

Return these sections:

1. **Backend Architecture Map**
2. **Confirmed Root Causes**
3. **Stale Listener Lifecycle Explanation**
4. **Doctor/Diagnosis Gaps**
5. **Complete Defect Table**
6. **Files Changed**
7. **Regression Tests Added**
8. **Exact Test Results**
9. **Safety Assessment**
10. **Deployment Package + SHA-256**
11. **Exact VPS Deployment Steps**
12. **Controlled Demo RUNNING Acceptance Steps**
13. **Infrastructure Demo Trade Acceptance Plan**
14. **Strategy #1 End-to-End Execution Verification Plan**
15. **Remaining Known Risks / Technical Debt**
16. **Final status: READY FOR VPS ACCEPTANCE or NOT READY**

### Critical directive

Do not treat `listener_count_valid` as the root cause.

It is the safety mechanism detecting the deeper lifecycle defect.

The current evidence strongly indicates stale `run_secure_staging_web.py` processes from earlier manager generations remain bound to `127.0.0.1:8080`.

Prove why they survive, fix that process lifecycle defect, improve Doctor so it can diagnose it automatically, audit the rest of the backend, and only then return a package.

The goal is not another local test pass.

The goal is a stable RC17 backend that can reliably reach RUNNING and then execute legitimate trades on ATLAS-DEMO so strategy performance data can finally be collected.
