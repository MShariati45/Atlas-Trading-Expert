from pathlib import Path
from types import SimpleNamespace

from atlas.execution.controlled_demo_gate import DemoExecutionTicket, ExecutionLedger, BrokerContract
from atlas.execution.demo_transport import DemoOnlyMT5Transport, DemoExecutionAuditLog
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.mt5_bridge import MT5PythonBridge, MT5ConnectionSettings

class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO=0; ACCOUNT_TRADE_MODE_REAL=2
    ORDER_TYPE_BUY=0; ORDER_TYPE_SELL=1; TRADE_ACTION_DEAL=1; TRADE_RETCODE_DONE=10009; ORDER_TIME_GTC=0; ORDER_FILLING_IOC=1
    def __init__(self, demo=True, expert=True, order_ok=True): self.demo=demo; self.expert=expert; self.order_ok=order_ok; self.sent=0
    def initialize(self, **kwargs): return True
    def last_error(self): return (0,'OK')
    def account_info(self): return SimpleNamespace(login=42, server='Broker-Demo' if self.demo else 'Broker-Live', trade_mode=0 if self.demo else 2, trade_allowed=True, trade_expert=self.expert)
    def symbol_select(self,*a): return True
    def symbol_info(self,*a): return SimpleNamespace()
    def symbol_info_tick(self,*a): return SimpleNamespace(ask=1.1000,bid=1.0999)
    def order_check(self,req): return SimpleNamespace(retcode=0 if self.order_ok else 99, comment='ok' if self.order_ok else 'bad')
    def order_send(self,req): self.sent += 1; return SimpleNamespace(retcode=10009, comment='Done', order=1, deal=2, price=req['price'])
    def positions_get(self,**kwargs): return (SimpleNamespace(ticket=3,magic=260826,time_msc=1,sl=1.095,tp=1.11,volume=1.0,price_open=1.1),)

def _ticket(): return DemoExecutionTicket('T','S','A','Broker-Demo','EURUSD','LONG',1.1,1.095,1.11,2.0,0.5,500,100000,1.0,5,5,7,'NORMAL',.1,'PASS','CLEAR','DEMO_ONLY','2026-08-20T00:00:00+00:00')
def _contract(): return BrokerContract(.0001,.0001,10,.01,100,.01,5)
def _run(tmp_path, fake):
    ledger=ExecutionLedger(tmp_path/'ledger.sqlite3'); t=_ticket(); ledger.claim(t)
    b=MT5PythonBridge({'A':MT5ConnectionSettings(symbol_map={'EURUSD':'EURUSD'})},execution_enabled=True); b._mt5=fake
    x=DemoOnlyMT5Transport(b,ledger=ledger,audit=DemoExecutionAuditLog(tmp_path/'audit.jsonl'))
    return x.execute(AccountConfig('A',True,.5,broker='Broker-Demo'),ApprovedSignal('S','EURUSD','LONG',1.1,1.095,1.11),t,expected_login=42,contract=_contract())

def test_demo_send_and_verify(tmp_path):
    f=FakeMT5(); r=_run(tmp_path,f); assert r.status=='VERIFIED'; assert f.sent==1

def test_real_account_blocked_before_send(tmp_path):
    f=FakeMT5(demo=False); r=_run(tmp_path,f); assert r.status=='BLOCKED'; assert f.sent==0

def test_expert_trading_disabled_blocks(tmp_path):
    f=FakeMT5(expert=False); r=_run(tmp_path,f); assert r.status=='BLOCKED'; assert f.sent==0

def test_order_check_failure_never_sends(tmp_path):
    f=FakeMT5(order_ok=False); r=_run(tmp_path,f); assert r.status=='FAILED'; assert f.sent==0
