import pytest

from atlas.accounts import ManagedAccountProfile, TraderAccountAssignmentService
from atlas.execution.account_identity import AccountIdentityDecision
from atlas.execution.account_state import AccountExecutionState, ExecutionConnectionState
from atlas.security import AccessPolicy, UserIdentity, UserRole
from atlas.staging import StagingUserService


def test_owner_can_assign_multiple_accounts_to_one_trader_and_trader_can_switch_read_only():
    owner = UserIdentity("O", "owner", UserRole.OWNER)
    trader = UserIdentity("T", "trader", UserRole.TRADER)
    trader = StagingUserService.assign_account(owner, trader, "A1")
    trader = StagingUserService.assign_account(owner, trader, "A2")
    trader = StagingUserService.assign_account(owner, trader, "A3")
    assert trader.account_ids == frozenset({"A1", "A2", "A3"})
    assert TraderAccountAssignmentService.validate_switch(trader, "A2") == "A2"
    assert AccessPolicy.can_view_account(trader, "A3")
    assert not AccessPolicy.can_control_account(trader, "A3")


def test_trader_cannot_switch_to_unassigned_account():
    trader = UserIdentity("T", "trader", UserRole.TRADER, frozenset({"A1", "A2"}))
    with pytest.raises(PermissionError):
        TraderAccountAssignmentService.validate_switch(trader, "A9")


def test_admin_and_trader_cannot_assign_customer_accounts():
    admin = UserIdentity("A", "admin", UserRole.ADMIN)
    trader = UserIdentity("T", "trader", UserRole.TRADER)
    other = UserIdentity("T2", "other", UserRole.TRADER)
    with pytest.raises(PermissionError):
        StagingUserService.assign_account(admin, trader, "A1")
    with pytest.raises(PermissionError):
        StagingUserService.assign_account(other, trader, "A1")


def test_trader_read_only_summary_contains_only_assigned_accounts():
    trader = UserIdentity("T", "trader", UserRole.TRADER, frozenset({"A1", "A3"}))
    profiles = [
        ManagedAccountProfile("A1", "T", "Primary", "Broker", "TERM-1"),
        ManagedAccountProfile("A2", "X", "Other", "Broker", "TERM-2"),
        ManagedAccountProfile("A3", "T", "Secondary", "Broker", "TERM-3"),
    ]
    rows = TraderAccountAssignmentService.build_read_only_summaries(
        trader,
        profiles,
        {"A1": {"balance": 10000, "equity": 10100, "today_pl": 100, "open_trades": 1},
         "A2": {"balance": 99999},
         "A3": {"balance": 25000, "equity": 24900, "today_pl": -100, "open_trades": 0}},
    )
    assert [x.account_id for x in rows] == ["A1", "A3"]
    assert rows[0].equity == 10100
    assert rows[1].today_pl == -100


def test_execution_connection_is_not_authorization_and_cannot_skip_states():
    s = AccountExecutionState("A1")
    assert s.state is ExecutionConnectionState.CONNECTED
    with pytest.raises(ValueError):
        s.enable_execution(explicit_demo_unlock=True)
    s = s.to_observation()
    with pytest.raises(PermissionError):
        s.authorize_demo(identity=AccountIdentityDecision(False,("NOT_DEMO",),1,"Broker-Live",2), safety_passed=True)
    s = s.authorize_demo(identity=AccountIdentityDecision(True,(),1,"Broker-Demo",0), safety_passed=True)
    assert s.state is ExecutionConnectionState.DEMO_AUTHORIZED
    s = s.enable_execution(explicit_demo_unlock=True)
    assert s.state is ExecutionConnectionState.EXECUTION_ENABLED


def test_execution_state_fail_closed_lock_returns_to_observation():
    s = AccountExecutionState("A1").to_observation().authorize_demo(identity=AccountIdentityDecision(True,(),1,"Broker-Demo",0), safety_passed=True)
    s = s.enable_execution(explicit_demo_unlock=True).lock()
    assert s.state is ExecutionConnectionState.OBSERVATION
    assert s.safety_passed is False
