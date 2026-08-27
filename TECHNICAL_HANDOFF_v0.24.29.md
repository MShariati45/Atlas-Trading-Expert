# Atlas v0.24.29 - Technical Handoff

## Scope
This checkpoint adds the supervised DEMO-only management boundary for existing Atlas positions. It does not alter the frozen entry strategy.

## Legal MT5 mutation paths
- New DEMO position: `ControlledDemoExecutionGate -> DemoOnlyMT5Transport`.
- Existing DEMO position management: `SupervisedDemoManagementGate -> DemoOnlyTradeManagementTransport`.
- Legacy direct `place_order`, `modify_stop`, and `close_position` remain disabled.

## Management actions implemented
- Move SL to breakeven at >= +1.4R, never loosening protection.
- Full Friday close on Friday.
- Full protective/news close only when explicitly authorized by upstream policy.
- Full Owner emergency close only when explicitly Owner-authorized.

## Safety properties
- MT5 `ACCOUNT_TRADE_MODE_DEMO` and expected login are rechecked immediately before every mutation.
- Broker position must map to the Atlas execution ledger by account + position + signal.
- Same transactional SQLite database stores entry claims and management claims.
- Management mutations use atomic idempotency keys.
- SEND_ATTEMPTED is durable before `order_send`; uncertain results require reconciliation and are never automatically retried.
- Broker state is verified after stop movement/full close.
- Hash-chained/fsynced audit is used for management events.

## Intentionally not implemented
- partial close;
- scale-in/scale-out;
- trailing-stop experiments;
- LIVE/REAL management;
- Trader/Admin arbitrary trade mutation from UI.

## Validation
- `python -m compileall -q atlas tests`: PASS
- `pytest -q`: 295 PASS
- runtime `order_send` call sites: only `demo_transport.py` and `trade_management.py`.
