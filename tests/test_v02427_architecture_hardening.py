import pytest

from atlas.core.sqlite_state_store import SQLiteStateStore
from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.execution.controlled_demo_gate import DemoExecutionTicket
from atlas.execution.mt5_bridge import MT5PythonBridge
from atlas.execution.models import AccountConfig, ApprovedSignal


def _ticket():
    return DemoExecutionTicket('T','S','A','Broker-Demo','EURUSD','LONG',1.1,1.095,1.11,2.0,0.5,500,100000,1.0,5,5,7,'NORMAL',.1,'PASS','CLEAR','DEMO_ONLY','2026-08-20T00:00:00+00:00')


def test_sqlite_state_store_atomic_update(tmp_path):
    a = SQLiteStateStore(tmp_path / 'state.sqlite3')
    b = SQLiteStateStore(tmp_path / 'state.sqlite3')
    a.set('counter', 0)
    for _ in range(5):
        a.update('counter', lambda x: x + 1, 0)
        b.update('counter', lambda x: x + 1, 0)
    assert a.get('counter') == 10


def test_sqlite_execution_ledger_unique_claim(tmp_path):
    a = SQLiteExecutionLedger(tmp_path / 'exec.sqlite3')
    b = SQLiteExecutionLedger(tmp_path / 'exec.sqlite3')
    a.claim(_ticket())
    with pytest.raises(PermissionError, match='DUPLICATE_SIGNAL_ACCOUNT_ALREADY_CLAIMED'):
        b.claim(_ticket())
    a.mark('A', 'S', 'VERIFIED', broker_order_id='123')
    assert b.get('A','S')['status'] == 'VERIFIED'


def test_legacy_direct_order_path_disabled_even_when_bridge_enabled():
    b = MT5PythonBridge(execution_enabled=True)
    a = AccountConfig('DEMO', True, 0.5, broker='Broker-Demo')
    s = ApprovedSignal('s','EURUSD','LONG',1.1,1.09,1.12)
    with pytest.raises(PermissionError, match='LEGACY_DIRECT_ORDER_PATH_DISABLED'):
        b.place_order(a, s, 0.01)
