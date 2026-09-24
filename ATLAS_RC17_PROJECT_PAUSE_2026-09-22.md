# Atlas RC17 — Project Pause & Continuation Note

**Project:** Atlas Trading Expert  
**Release:** Atlas-0.25.0-rc17-FINAL  
**Project pause date:** September 22, 2026  
**Archive note:** September 23, 2026  
**Repository:** MShariati45/Atlas-Trading-Expert  
**VPS root at pause:** `C:\Atlas2\Atlas-0.25.0-rc17-FINAL`

## Status

Atlas RC17 is intentionally **PAUSED**, not abandoned.

Development was paused after extensive work on controlled Demo execution because the system had become too complex relative to the immediate objective: connect a trading strategy to MetaTrader 5, execute legitimate Demo trades reliably, and collect useful performance data.

The detailed technical state immediately before the pause is preserved in the repository in the September 22, 2026 **ATLAS RC17 — Full Engineering Handoff and Audit Report**. That report remains the authoritative engineering handoff and should not be replaced or rewritten.

## Reason for Pause

Atlas had not yet demonstrated repeatable end-to-end Strategy #1 trade execution on the ATLAS-DEMO MT5 account.

The final investigation reached two important areas:

1. The real MT5 path reached `mt5.order_check(request)`, which returned `None`; Atlas correctly did not call `order_send()`.
2. Subsequent restart/diagnostic work exposed Windows process-lifecycle and stale web-listener problems around the RC17 controlled runtime.

The September 22 full audit handoff contains the detailed evidence, diagnostics, process IDs, safety state, test results, and recommended continuation plan.

## Preservation Decision

Before repurposing the Windows trading environment, preserve the GitHub repository and full commit history, the September 22 full engineering handoff, this pause note, the Obsidian Atlas vault, and any unique local evidence/configuration that is not already archived and is safe to preserve.

Do not commit passwords, broker credentials, API keys, authentication secrets, or other sensitive account data to GitHub.

## Current Direction — Diana Expert

The immediate development focus is a separate project named **Diana Expert**.

Diana is intended to be a simpler, standalone native MetaTrader 5 Expert Advisor. It should avoid reproducing Atlas's multi-layer architecture unless a layer is clearly necessary.

Atlas and Diana are separate projects. Diana development must not overwrite Atlas history or change Strategy #1 simply to make Atlas trade.

## Future Atlas Continuation

When Atlas work resumes:

1. Start from this repository and the September 22 full engineering handoff.
2. Treat `Atlas-0.25.0-rc17-FINAL` as the paused RC17 target unless a deliberate new release is created.
3. Re-audit the runtime/process lifecycle before attempting new patches.
4. Resolve stale managed listener/process cleanup at the root cause rather than weakening fail-closed ownership checks.
5. Restore a reliable controlled Demo `RUNNING` state.
6. Return to the original MT5 `order_check()` diagnostic path.
7. Prove infrastructure Demo execution separately from Strategy #1 signal availability.
8. Prove that a legitimate Strategy #1 candidate can traverse the normal path to MT5 without changing the strategy merely to force a trade.
9. Keep Live/Real Money disabled until a future explicit acceptance decision.

## Archive References

- GitHub: `MShariati45/Atlas-Trading-Expert`
- Full audit handoff commit: `4358fa9e96cd7da97cc204b36203822470539066`
- Commit message: `Atlas Full Audit Handoff-2026,09,22`
- Obsidian vault: `C:\Users\Mehdi\Documents\Atlas Trading Expert`
- Obsidian destination: `10 - DAILY HANDOFFS`

---

**Continuation trigger:** When the owner decides to resume Atlas, read the September 22 full engineering handoff and this pause note before making any code or deployment changes.
