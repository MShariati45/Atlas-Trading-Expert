from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from pathlib import Path
import json, os

from atlas.execution.account_state import AccountExecutionState
from atlas.execution.controlled_demo_gate import BrokerContract, ControlledDemoExecutionGate, ExecutionLedger
from atlas.execution.demo_authorization import DemoExecutionAuthorizer
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.services.adaptive_spread_guard import AdaptiveSpreadGuard
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.services.live_news import LiveNewsGuardService
from atlas.services.news_provider import NewsProviderStatus
from atlas.execution.risk_state import StaticAccountRiskStateService, AccountRiskSnapshot
from atlas.execution.account_identity import AccountIdentityDecision

with TemporaryDirectory() as td:
    p=Path(td)
    (p/'preflight.json').write_text(json.dumps({'ready_for_paper_supervision':True,'account':{'server':'MetaQuotes-Demo'}}))
    (p/'enable.json').write_text(json.dumps({'mode':'DEMO_ONLY','enabled':True}))
    os.environ['ATLAS_DEMO_EXECUTION']='YES'
    h4=H4HumanApprovalStore(path=p/'h4.json')
    h4.approve('EURUSD','BULLISH',1.08,1.10,note='owner')
    auth=DemoExecutionAuthorizer(approval_store=h4, enable_file=p/'enable.json', preflight_file=p/'preflight.json')
    spread=AdaptiveSpreadGuard({'symbols':{'EURUSD':{'all':{'median_points':5.0,'p95_points':7.0},'sessions':{}}}})
    provider=type('P',(),{'status':NewsProviderStatus(True,'SELF',0,None),'events':lambda self,now=None: []})()
    gate=ControlledDemoExecutionGate(authorizer=auth, spread_guard=spread, news_service=LiveNewsGuardService(provider), risk_state_service=StaticAccountRiskStateService(AccountRiskSnapshot(True,0,0,0.0,False)), ledger=ExecutionLedger(p/'ledger.sqlite3'))
    account=AccountConfig('MY-DEMO',True,0.5,broker='MetaQuotes-Demo')
    state=AccountExecutionState('MY-DEMO').to_observation().authorize_demo(identity=AccountIdentityDecision(True,(),42,'MetaQuotes-Demo',0),safety_passed=True).enable_execution(explicit_demo_unlock=True)
    signal=ApprovedSignal('selfcheck','EURUSD','LONG',1.1000,1.0950,1.1100)
    contract=BrokerContract(0.0001,0.0001,10.0,0.01,100.0,0.01,5)
    d=gate.prepare(account,state,signal,account_server='MetaQuotes-Demo',equity=100000,contract=contract,current_spread_points=5.0,now=datetime(2026,8,20,15,0,tzinfo=timezone.utc))
    print(json.dumps({'atlas_version':'0.24.25','gate_allowed':d.allowed,'ticket':d.ticket.to_dict() if d.ticket else None,'zero_ai_calls':True,'orders_sent':0},indent=2))
