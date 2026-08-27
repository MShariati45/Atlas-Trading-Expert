# Atlas v0.24.0 - Live News Agent Readiness

## Purpose
This checkpoint hardens the News Agent before paper supervision. News remains a hard safety gate and cannot authorize a trade by itself.

## Production news contract
A production news schedule must provide:
- `generated_at_utc`
- `valid_until_utc`
- `source_name`
- `source_url`
- `coverage_currencies` covering **USD, EUR, CAD, JPY**
- scheduled events with UTC timestamps and HIGH/MEDIUM/LOW impact labels

Events may specify `affected_symbols` directly or currencies. Currency events are mapped to the active Atlas watchlist:
- USD -> EURUSD, USDJPY, USDCAD, XAUUSD
- EUR -> EURUSD
- JPY -> USDJPY
- CAD -> USDCAD

A fresh but partial schedule is not paper-ready. Missing any required currency causes the News Provider to be unavailable and Supervisor must WAIT.

## Official-source validation path
`run_official_us_news_refresh.bat` fetches the official U.S. Bureau of Labor Statistics ICS release calendar. This verifies zero-cost, no-AI official-source ingestion for U.S. macro releases. It is deliberately marked **USD partial coverage only** and can never make paper supervision ready on its own.

Atlas classifies BLS Employment Situation, CPI, PPI, and Employment Cost Index as HIGH for the News Guard. Other BLS entries are retained as MEDIUM.

## Multi-currency production path
`run_live_news_refresh.bat` remains the provider-neutral path for a trusted/licensed multi-currency calendar feed. v0.24.0 now rejects feeds that are stale, lack provenance, or do not cover USD/EUR/CAD/JPY.

## Safety behavior
- Default pre-entry blackout: 120 minutes for HIGH-impact events.
- Missing/unavailable/stale/incomplete news data -> tri-state UNKNOWN -> Supervisor WAIT.
- News cannot mutate H4/H1/M15 analysis.
- News cannot enable execution.
- MT5 execution bridge remains hard locked.
- No AI calls are required for schedule ingestion.

## Research vs trading news
The Research/Education Supervisor's publication monitoring is separate from the scheduled News Agent. Research publications may educate agents and create proposals, but cannot change live rules without validation and approval.
