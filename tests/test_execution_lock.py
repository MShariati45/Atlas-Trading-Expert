import pytest
from atlas.execution.mt5_bridge import MT5PythonBridge
from atlas.execution.models import AccountConfig, ApprovedSignal


def test_mt5_mutations_are_hard_locked_by_default():
    b=MT5PythonBridge()
    a=AccountConfig('DEMO', True, 0.5, broker='MT5_DEMO')
    s=ApprovedSignal('s1','EURUSD','LONG',1.1,1.09,1.12)
    with pytest.raises(PermissionError, match='MT5_EXECUTION_DISABLED'):
        b.place_order(a,s,0.01)
    with pytest.raises(PermissionError, match='MT5_EXECUTION_DISABLED'):
        b.modify_stop(a,'1',1.1)
    with pytest.raises(PermissionError, match='MT5_EXECUTION_DISABLED'):
        b.close_position(a,'1')
