# Atlas Trading Expert - GitHub Handoff

## Checkpoint
Date: 2026-08-28
Primary package: `C:\Atlas\Atlas_v0.24.32_TLS_Deployment_Boundary`

## Current operating state
- Private staging web application is running.
- Environment remains DEMO / STAGING.
- Real-money execution remains disabled/locked.
- MT5 demo terminal connection is active.
- Current watchlist: EURUSD, USDJPY, USDCAD, XAUUSD.
- Dashboard and Watchlist pages are loading normally.

## Approved Watchlist visual design
The Watchlist visual direction is frozen as the approved target:
- Strongly separated symbol cards.
- Distinct instrument identity treatment for EURUSD, USDJPY, USDCAD, XAUUSD.
- Large pair icon area at the left of each symbol card.
- Bid / Ask and Spread grouped directly with each symbol.
- H4 Structure, H1 Structure, M15 Setup and Supervisor each shown as their own status tile.
- Bullish state uses neon green and bull visual language.
- Bearish state uses neon red and bear visual language.
- WAIT / review state uses neon yellow.
- Idle / neutral state uses muted blue-gray.
- Active Pattern, News, Risk and Last Update remain grouped on the right side of the same symbol card.
- Clicking a symbol card continues to open the H4 Strategic Checkpoint.
- Top Watchlist summary remains: Symbols, Setup Forming, Review Required, Active Trades, News Status.
- Universal status strip remains at the top: Mode, MT5 Terminal, Market Status, API Status, Local Time.
- Sidebar page controls use Atlas-specific icon/key styling; final cosmetic refinement can happen later.

## Approved H4 Strategic Checkpoint direction
Target layout:
1. Universal status strip.
2. Selected symbol - H4 Strategic Checkpoint header.
3. Large real M15 candlestick chart as the main visual element.
4. Atlas H4 assessment panel beside the chart.
5. Structure summary.
6. Trading restrictions section.
7. Owner H4 confirmation / override controls.

The chart should ultimately show:
- Real completed M15 candles from MT5.
- Current M15 pattern / setup information from Atlas.
- H4/H1 structure context and important levels where available.
- Potential entry / SL / TP overlays later when safely supported.

## Backend architecture discovered
Read-only web chain:
`/api/watchlist` -> `APP.watchlist(user)` -> `AtlasReadModelService.watchlist()` -> `runtime/dashboard_state.json`

Important files:
- `run_secure_staging_web.py`
- `atlas\api\app_service.py`
- `atlas\api\read_models.py`
- `run_dashboard_activation.py`
- `atlas\market_data\live_runtime.py`
- `atlas\market_data\mt5_feed.py`
- `atlas\market_data\m15_strategy_runtime.py`
- `atlas\market_data\m15_live_runtime.py`

`AtlasReadModelService` intentionally reads persisted Atlas state and execution ledger only. It does not import an MT5 bridge or order transport.

## M15 chart-data work completed tonight
A patch was added to `run_dashboard_activation.py` to collect completed M15 candles for the web dashboard using the existing read-only market-data feed.

Patch script created:
`C:\Atlas\add_m15_chart_state.ps1`

Patch behavior:
- Requests 120 completed M15 candles per watchlist symbol.
- Adds an `m15_chart` payload to watchlist rows.
- Attaches existing M15 strategy snapshot data.
- Runs Python syntax validation.
- Creates a timestamped backup before modification.

Patch completed successfully and Python syntax validation passed.

`run_dashboard_activation.py --once` also completed successfully with:
`dashboard snapshot: READ_ONLY_DEMO_OBSERVATION; execution=LOCKED`

## Unresolved issue / exact restart point for tomorrow
The persisted `runtime/dashboard_state.json` did not visibly expose the expected `m15_chart` payload during verification.

Do NOT redo the architecture search tomorrow.
Start here:
1. Inspect the first Watchlist row property names in the fresh `runtime/dashboard_state.json`.
2. Determine whether another continuously running Atlas process is overwriting `dashboard_state.json` after the one-shot activation run.
3. Identify the continuous writer if necessary.
4. Once the M15 chart payload persists reliably, expose it through the read-only API and render the H4 Strategic Checkpoint candlestick chart.

Known running Python services at the checkpoint:
- `run_shadow_paper_supervisor.py`
- `run_supervised_demo_runtime.py --poll-seconds 15`
- `run_m15_first_observer.py`
- `run_secure_staging_web.py --host 127.0.0.1 --port 8080`

No continuous `run_dashboard_activation.py` process was visible when processes were inspected.

## Safety constraints
Do not change:
- DEMO / STAGING boundary.
- `execution_enabled = false` behavior.
- `trade_allowed = false` behavior.
- REAL MONEY DISABLED protection.
- Existing order/execution transport boundaries.

Do not add a second independent MT5 connection for the web UI. Reuse the existing read-only market-data architecture.

## Tomorrow priority order
1. Confirm persisted M15 chart payload and identify overwrite behavior if present.
2. Finish H4 Strategic Checkpoint visual layout and real M15 chart.
3. Preserve approved Watchlist visual design.
4. Continue Accounts page after H4 page is stable.
5. Leave micro-cosmetics for the dedicated cosmetic pass.
