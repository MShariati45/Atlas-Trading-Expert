"""Offline v0.24.22 integration self-check. No MT5 orders and no AI/API calls."""
from __future__ import annotations
import json
from pathlib import Path
from atlas.security import UserRole, UserIdentity, AccessPolicy
from atlas.accounts import TraderAccountAssignmentService
from atlas.execution.account_state import AccountExecutionState, ExecutionConnectionState


def main() -> int:
    root=Path(__file__).resolve().parent
    cfg=json.loads((root/'config'/'atlas_m15_first_v0.24.4.json').read_text(encoding='utf-8'))
    owner=UserIdentity('OWNER','owner',UserRole.OWNER)
    trader=UserIdentity('TRADER','trader',UserRole.TRADER)
    trader=TraderAccountAssignmentService.assign(owner,trader,'DEMO-A')
    trader=TraderAccountAssignmentService.assign(owner,trader,'DEMO-B')
    state=AccountExecutionState('DEMO-A').to_observation()
    checks={
      'version_0_24_22': (root/'VERSION').read_text().strip()=='0.24.22',
      'roles_exact': {r.value for r in UserRole}=={'OWNER','ADMIN','TRADER'},
      'one_trader_many_accounts': trader.account_ids==frozenset({'DEMO-A','DEMO-B'}),
      'trader_read_only': AccessPolicy.can_view_account(trader,'DEMO-A') and not AccessPolicy.can_control_account(trader,'DEMO-A'),
      'account_switch_guard': TraderAccountAssignmentService.validate_switch(trader,'DEMO-B')=='DEMO-B',
      'connection_not_authorization': state.state is ExecutionConnectionState.OBSERVATION,
      'demo_lifecycle_configured': cfg.get('demo_readiness',{}).get('connection_does_not_imply_authorization') is True,
      'owner_only_assignment_configured': cfg.get('multi_account',{}).get('owner_only_account_assignment') is True,
      'execution_transport_locked': cfg.get('multi_account',{}).get('execution_transport')=='DEMO_ONLY_LOCKED_UNTIL_EXPLICIT_AUTHORIZATION',
    }
    failed=[k for k,v in checks.items() if not v]
    print(json.dumps({'atlas_version':'0.24.22','mode':'OFFLINE_STAGING_SELFCHECK','checks':checks,'passed':not failed,'failed':failed,'zero_ai_calls':True,'orders_sent':False},indent=2))
    return 1 if failed else 0

if __name__=='__main__':
    raise SystemExit(main())
