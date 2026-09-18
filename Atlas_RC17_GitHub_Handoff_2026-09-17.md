# Atlas RC17 - GitHub Handoff

Date: September 17, 2026

## Current State

Deployment: `C:\Atlas2\Atlas-0.25.0-rc17-FINAL` Protected baseline:
RC16 - UNTOUCHED Safety: REAL MONEY DISABLED

## Completed Today

Three operational-diagnostic corrections were deployed.

### 1. MT5 Diagnosis Supersession

Fixed historical MT5 executable failure evidence overriding the
repaired/reinstalled executable.

Package: `RC17-FINAL-diagnosis-supersession-v1.zip` SHA-256:
`F0A4843A34275AAF94A60B66F1EEB00BDC7F317E02EC03131AFC7E1D3017C199`

Implemented executable-generation identity/fingerprinting,
evidence-authority ordering, legacy-report downranking,
superseded-evidence preservation, and UUID correlation for new launches.

### 2. Web Endpoint Identity

Fixed Doctor probing the wrong/default web port when invoked outside the
managed child environment.

Package: `RC17-FINAL-web-endpoint-identity-v1.zip` SHA-256:
`13A44B9567153254F196943BA65B8F5725FA5F801617B7772F5CE7BADF8A06C9`

WEB_API heartbeat now retains port, Atlas version, and endpoint
identity. Endpoint resolution uses authoritative current evidence and
conflicts fail closed.

### 3. Canonical Loopback Health Contract

Fixed `/health` being rejected by the deployment Host boundary during
direct loopback readiness checks.

Package: `RC17-FINAL-loopback-health-contract-v1.zip` SHA-256:
`30B12DA82B17FB2B7FF66B7C0D1880FE174F2D991ECB3100A25CEAC8E29EFA46`

Deployment validation: 81 passed.

The shared readiness contract now returns:
`{"status":"ok","atlas_version":"0.25.0-rc17"}`

Normal Host/security protections remain in place for application pages,
authenticated APIs, system-health APIs, and sensitive POST routes.

## Verified Runtime

WEB_API is RUNNING on port 8080. Atlas version: `0.25.0-rc17` Endpoint
identity: `RC17_LOOPBACK_HEALTH_V1` Health path: `/health`

Managed Demo chain: - manager_authorized = true - runtime_authorized =
true - account_manager_authorized = true - demo_worker_authorized =
true - verified = true - real_money = DISABLED

Service manager, supervised Demo runtime, account-worker manager, and
MT5 account worker are running.

## Latest Doctor

``` text
ATLAS DIAGNOSIS
SYSTEM: DEGRADED
PRIMARY ROOT CAUSE: NONE
IMPACT: No blocking operational diagnosis was found.
REAL MONEY: DISABLED
```

The previous false MT5 executable and WEB_ENDPOINT blockers are gone.

## Exact Stopping Point

One Diagnosis Center semantic issue remains: Doctor reports
`SYSTEM: DEGRADED` while reporting no primary root cause and no blocking
operational diagnosis.

A filtered deep-diagnosis search did not expose an explicit
DEGRADED/WARNING/ERROR/BLOCKED/CRITICAL/STALE diagnostic state
explaining the global result.

No further code changes were made.

## Tomorrow - First Task

Audit: **RC17-FINAL - INVESTIGATE DOCTOR DEGRADED WITH NO REPORTED
ISSUE**

Determine the exact evidence and aggregation path producing global
DEGRADED.

Do not simply change DEGRADED to HEALTHY. Overall state must remain
evidence-driven. If DEGRADED is legitimate, Doctor must expose the
specific current reason, affected component, and impact. If an expected
condition incorrectly promotes global health to DEGRADED, correct the
aggregation semantics. Historical/superseded evidence must not degrade
current system health.

Audit first; no implementation until reviewed.

## After Diagnosis Cleanup

1.  Verify Strategy #1 / M15 detection pipeline without loosening
    strategy.
2.  Verify controlled Demo execution from valid Strategy #1 signals.
3.  Correct News UI semantics so BLOCKED means an actual configured
    news-protection window.
4.  Verify Symbol Detail H4 Owner impulse
    confirmation/modification/reset and shared Laboratory state.
5.  Finish remaining frontend cosmetics, including the homepage-logo
    correction.
6.  Continue SuperTrend only as separate Strategy #2 research after
    Strategy #1 and RC17 operational stability.

## Safeguards

-   Strategy #1 unchanged unless explicitly working against its verified
    specification.
-   RC16 untouched.
-   Real Money disabled.
-   SuperTrend remains separate/research-only.
-   Diagnostics remain read-only.
-   Diagnostics must not enable execution, alter credentials, terminate
    uncertain processes, or submit orders.
-   Demo execution remains controlled authorization only.
