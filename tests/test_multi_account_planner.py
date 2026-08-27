from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.execution.multi_account_planner import MultiAccountExecutionPlanner


def test_one_signal_builds_isolated_account_risk_plans():
    sig=ApprovedSignal('s1','EURUSD','LONG',1.1,1.09,1.12)
    accounts=[
        AccountConfig('A',True,0.5,broker='B1'),
        AccountConfig('B',True,0.3,broker='B2'),
        AccountConfig('C',False,0.5,broker='B3'),
    ]
    plans=MultiAccountExecutionPlanner().build(sig,accounts,{'A':100000,'B':200000,'C':100000})
    assert [p.account_id for p in plans]==['A','B']
    assert plans[0].risk_cash==500
    assert plans[1].risk_cash==600
    assert all(p.symbol=='EURUSD' for p in plans)
