from atlas.accounts import ManagedAccountProfile, MultiTerminalAccountOrchestrator
from atlas.reporting import AccountReportBuilder, TrainingReportBuilder
from atlas.security import AccessPolicy, PasswordHasher, UserIdentity, UserRole


def test_multi_terminal_workers_are_isolated_one_terminal_per_account():
    accounts = [
        ManagedAccountProfile("A1", "U1", "Alpha", "BrokerA", "TERM-A", risk_pct=0.3),
        ManagedAccountProfile("A2", "U2", "Beta", "BrokerB", "TERM-B", risk_pct=0.6),
    ]
    specs = MultiTerminalAccountOrchestrator().build_worker_specs(accounts)
    assert [s.account_id for s in specs] == ["A1", "A2"]
    assert all(s.isolation_mode == "ONE_PROCESS_PER_TERMINAL_ACCOUNT" for s in specs)


def test_duplicate_terminal_is_rejected():
    accounts = [
        ManagedAccountProfile("A1", "U1", "Alpha", "BrokerA", "TERM-X"),
        ManagedAccountProfile("A2", "U2", "Beta", "BrokerB", "TERM-X"),
    ]
    try:
        MultiTerminalAccountOrchestrator().build_worker_specs(accounts)
    except ValueError as exc:
        assert "terminal instance reused" in str(exc)
    else:
        raise AssertionError("expected isolation failure")


def test_trader_sees_only_assigned_accounts_and_cannot_control_them():
    trader = UserIdentity("U1", "trader1", UserRole.TRADER, frozenset({"A1"}))
    assert AccessPolicy.can_view_account(trader, "A1")
    assert not AccessPolicy.can_view_account(trader, "A2")
    assert not AccessPolicy.can_control_account(trader, "A1")
    assert not AccessPolicy.can_view_research(trader)


def test_owner_alone_can_create_users_and_attach_accounts():
    owner = UserIdentity("OWNER", "owner", UserRole.OWNER)
    admin = UserIdentity("ADMIN", "admin", UserRole.ADMIN)
    trader = UserIdentity("TRADER", "trader", UserRole.TRADER, frozenset({"A1"}))
    assert AccessPolicy.can_manage_users(owner)
    assert AccessPolicy.can_manage_accounts(owner)
    assert not AccessPolicy.can_manage_users(admin)
    assert not AccessPolicy.can_manage_accounts(admin)
    assert not AccessPolicy.can_manage_users(trader)


def test_password_hashing_is_salted_and_verifiable():
    a = PasswordHasher.hash_password("correct-horse-battery")
    b = PasswordHasher.hash_password("correct-horse-battery")
    assert a.digest_hex != b.digest_hex
    assert PasswordHasher.verify("correct-horse-battery", a)
    assert not PasswordHasher.verify("wrong-password-value", a)


def test_reports_separate_accounts_and_training_view_redacts_identity():
    rows = [
        {"account_id":"A1","owner_name":"Alice","login":111,"pattern":"FLAG_PENNANT","r_result":2.0},
        {"account_id":"A1","owner_name":"Alice","login":111,"pattern":"FLAG_PENNANT","r_result":-1.0},
        {"account_id":"A2","owner_name":"Bob","login":222,"pattern":"TRIANGLE_WEDGE","r_result":2.0},
    ]
    reports = AccountReportBuilder().build_all(rows)
    assert set(reports) == {"A1","A2"}
    assert reports["A1"].summary["net_r"] == 1.0
    assert reports["A2"].summary["net_r"] == 2.0
    training = TrainingReportBuilder().build(reports)
    assert training["mode"] == "TRAINING_ANONYMIZED"
    for row in training["records"]:
        assert "account_id" not in row
        assert "owner_name" not in row
        assert "login" not in row
