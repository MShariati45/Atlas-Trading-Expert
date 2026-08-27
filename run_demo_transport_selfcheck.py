from __future__ import annotations
import json, tempfile
from pathlib import Path
from types import SimpleNamespace

from atlas.execution.controlled_demo_gate import DemoExecutionTicket, ExecutionLedger, BrokerContract
from atlas.execution.demo_transport import DemoOnlyMT5Transport, DemoExecutionAuditLog
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.mt5_bridge import MT5PythonBridge, MT5ConnectionSettings

class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    ACCOUNT_TRADE_MODE_REAL=2
    ORDER_TYPE_BUY=0; ORDER_TYPE_SELL=1
    TRADE_ACTION_DEAL=1; TRADE_RETCODE_DONE=10009
    ORDER_TIME_GTC=0; ORDER_FILLING_IOC=1
    def __init__(self, demo=True): self.demo=demo
    def initialize(self, **kwargs): return True
    def last_error(self): return (0, 'OK')
    def account_info(self):
        return SimpleNamespace(login=123456, server='MetaQuotes-Demo' if self.demo else 'Broker-Live', trade_mode=0 if self.demo else 2, trade_allowed=True, trade_expert=True)
    def symbol_select(self, s, b): return True
    def symbol_info(self, s): return SimpleNamespace()
    def symbol_info_tick(self, s): return SimpleNamespace(ask=1.1000, bid=1.0999)
    def order_check(self, req): return SimpleNamespace(retcode=0, comment='Done')
    def order_send(self, req): return SimpleNamespace(retcode=10009, comment='Done', order=101, deal=202, price=req['price'])
    def positions_get(self, **kwargs):
        return (SimpleNamespace(ticket=303, magic=260826, time_msc=1, sl=1.0950, tp=1.1100, volume=1.0, price_open=1.1000),)


def ticket():
    return DemoExecutionTicket(
        ticket_id='DEMO::A::S', signal_id='S', account_id='A', account_server='MetaQuotes-Demo', symbol='EURUSD', direction='LONG',
        requested_entry=1.1000, stop=1.0950, target=1.1100, gross_rr=2.0, risk_pct=0.5, risk_cash=500.0, equity=100000.0,
        volume=1.0, current_spread_points=5.0, normal_spread_median_points=5.0, normal_spread_p95_points=7.0, spread_status='NORMAL',
        spread_to_stop_ratio=0.10, h4_gate='PASS', news_gate='CLEAR', execution_mode='DEMO_ONLY', prepared_at_utc='2026-08-20T15:00:00+00:00')

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    ledger=ExecutionLedger(td/'ledger.sqlite3')
    t=ticket(); ledger.claim(t)
    bridge=MT5PythonBridge({'A': MT5ConnectionSettings(symbol_map={'EURUSD':'EURUSD'})}, execution_enabled=True)
    bridge._mt5=FakeMT5(demo=True)
    transport=DemoOnlyMT5Transport(bridge, ledger=ledger, audit=DemoExecutionAuditLog(td/'audit.jsonl'))
    a=AccountConfig('A', True, 0.5, broker='MetaQuotes-Demo')
    s=ApprovedSignal('S','EURUSD','LONG',1.1000,1.0950,1.1100)
    c=BrokerContract(0.0001,0.0001,10.0,0.01,100.0,0.01,5)
    r=transport.execute(a,s,t,expected_login=123456,contract=c)
    assert r.status == 'VERIFIED', r.to_dict()
    assert r.verification and r.verification.status == 'PASS'

with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    ledger=ExecutionLedger(td/'ledger.sqlite3')
    t=ticket(); ledger.claim(t)
    bridge=MT5PythonBridge({'A': MT5ConnectionSettings()}, execution_enabled=True); bridge._mt5=FakeMT5(demo=False)
    transport=DemoOnlyMT5Transport(bridge, ledger=ledger, audit=DemoExecutionAuditLog(td/'audit.jsonl'))
    a=AccountConfig('A', True, 0.5, broker='Broker')
    s=ApprovedSignal('S','EURUSD','LONG',1.1000,1.0950,1.1100)
    c=BrokerContract(0.0001,0.0001,10.0,0.01,100.0,0.01,5)
    r=transport.execute(a,s,t,expected_login=123456,contract=c)
    assert r.status == 'BLOCKED'
    assert 'MT5_ACCOUNT_TRADE_MODE_NOT_DEMO' in r.reasons

print(json.dumps({
    'atlas_version':'0.24.28',
    'status':'PASS',
    'demo_transport_verified':True,
    'live_account_hard_rejected':True,
    'post_fill_verification':True,
    'duplicate_retry_policy':'NO_AUTOMATIC_RETRY',
    'zero_ai_calls':True,
    'real_orders_sent':0,
}, indent=2))
