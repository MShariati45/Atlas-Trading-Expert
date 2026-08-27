# Atlas Research & Education Governance v0.23.6

## Purpose
Atlas separates **trading state** from **education/research memory**. Market agents remain deterministic and independent. The Research/Education Supervisor can monitor trusted publications, store verified lessons, and persist human corrections, but it cannot mutate live strategy rules or upstream agent state.

## Trusted-source priority
Tier-1 public sources are preferred: Federal Reserve/FOMC and Monetary Policy Report, ECB Economic Bulletin, Bank of Canada Monetary Policy Report and surveys, Bank of Japan monetary-policy releases, BIS Quarterly Review/Triennial Survey research, and IMF WEO/GFSR. Public research from major commercial banks may be added later only when legally/publicly accessible and source identity is verifiable; paywalled material is not scraped.

Classical books are retained as bibliographic/reference anchors only (Murphy; Edwards & Magee/Bassetti; Bulkowski). Atlas does not store or reproduce copyrighted books. Any rule inspired by a book must be written as a concise independently stated rule and empirically validated before promotion.

## Learning model
1. Source monitor checks authoritative landing pages off-hours using normal HTTPS; this costs no AI API tokens.
2. A changed source is a **research event**, not a trading signal.
3. Human or optional AI review produces a versioned `Lesson` with source URL, evidence hash and intended audience.
4. User corrections are stored as persistent `Correction` records by agent.
5. Lessons/corrections are advisory memory. They never silently rewrite live agent code, pattern permissions, risk, or targets.
6. A proposed trading-rule change requires explicit promotion into code/profile, historical/replay validation, regression tests and user approval.

## Non-interference
H4 reads H4 data only; H1 reads H1 data only. M15 specialists do not import or mutate one another. Coordinator combines reports. Supervisor gates decisions but does not rewrite analytical state. Research/Education Supervisor cannot approve trades.

## Cost policy
AI remains disabled by default. Source monitoring itself uses no LLM. If AI is enabled later, it is limited to event-driven advisory/off-hours research/post-trade review, subject to caching plus daily/monthly caps. No candle-by-candle LLM polling is permitted.
