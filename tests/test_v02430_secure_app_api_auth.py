from __future__ import annotations

from pathlib import Path
import threading

import pytest

from atlas.api import AtlasPrivateAppService
from atlas.security import SQLiteAuthStore, TOTP, UserRole
from atlas.staging import LeadStore


def _store(tmp_path: Path) -> SQLiteAuthStore:
    return SQLiteAuthStore(tmp_path / "auth.sqlite3")


def _bootstrap(store: SQLiteAuthStore, *, username: str = "owner"):
    secret = TOTP.generate_secret()
    owner = store.create_user(actor=None, username=username, password="CorrectHorseBattery1!", role=UserRole.OWNER, mfa_secret=secret)
    return owner, secret


def test_owner_mfa_login_session_csrf_and_logout(tmp_path: Path):
    store = _store(tmp_path)
    owner, secret = _bootstrap(store)
    now = 1_800_000_000
    code = TOTP.code(secret, at_epoch=now)
    # Verify TOTP deterministically first, then use current code for authentication.
    assert TOTP.verify(secret, code, at_epoch=now)
    session = store.authenticate(username=owner.username, password="CorrectHorseBattery1!", mfa_code=TOTP.code(secret), ip="127.0.0.1")
    assert session is not None
    assert store.resolve_session(session.token) == owner
    assert store.validate_csrf(session.token, session.csrf_token)
    assert not store.validate_csrf(session.token, "wrong")
    store.revoke_session(session.token)
    assert store.resolve_session(session.token) is None


def test_wrong_mfa_and_wrong_password_fail(tmp_path: Path):
    store = _store(tmp_path)
    owner, secret = _bootstrap(store)
    assert store.authenticate(username=owner.username, password="wrong-wrong-wrong", mfa_code=TOTP.code(secret)) is None
    assert store.authenticate(username=owner.username, password="CorrectHorseBattery1!", mfa_code="000000") is None


def test_owner_only_user_creation_and_multi_account_assignment(tmp_path: Path):
    store = _store(tmp_path)
    owner, _ = _bootstrap(store)
    leads = LeadStore(tmp_path / "leads.jsonl")
    app = AtlasPrivateAppService(auth=store, leads=leads)
    trader = app.create_user(owner, username="trader1", password="LongTraderPassword1!", role="TRADER", account_ids=["A1"])
    assert trader["account_ids"] == ["A1"]
    updated = app.assign_account(owner, trader_user_id=trader["user_id"], account_id="A2")
    assert updated["account_ids"] == ["A1", "A2"]
    trader_identity = store.get_user(trader["user_id"])
    assert trader_identity is not None
    with pytest.raises(PermissionError):
        app.create_user(trader_identity, username="nope", password="LongTraderPassword2!", role="TRADER")


def test_trader_is_read_only_and_cannot_view_leads(tmp_path: Path):
    store = _store(tmp_path)
    owner, _ = _bootstrap(store)
    app = AtlasPrivateAppService(auth=store, leads=LeadStore(tmp_path / "leads.jsonl"))
    trader_d = app.create_user(owner, username="trader", password="LongTraderPassword1!", role="TRADER", account_ids=["D1", "D2"])
    trader = store.get_user(trader_d["user_id"])
    assert trader is not None
    assert app.list_accounts(trader) == [
        {"account_id": "D1", "read_only": True},
        {"account_id": "D2", "read_only": True},
    ]
    with pytest.raises(PermissionError):
        app.list_leads(trader)


def test_suspend_revokes_existing_sessions(tmp_path: Path):
    store = _store(tmp_path)
    owner, _ = _bootstrap(store)
    trader = store.create_user(actor=owner, username="trader", password="LongTraderPassword1!", role=UserRole.TRADER, require_mfa=False)
    session = store.authenticate(username="trader", password="LongTraderPassword1!")
    assert session is not None
    assert store.resolve_session(session.token) is not None
    store.set_enabled(actor=owner, user_id=trader.user_id, enabled=False)
    assert store.resolve_session(session.token) is None


def test_bootstrap_only_once(tmp_path: Path):
    store = _store(tmp_path)
    _bootstrap(store)
    with pytest.raises(PermissionError):
        store.create_user(actor=None, username="owner2", password="CorrectHorseBattery2!", role=UserRole.OWNER, mfa_secret=TOTP.generate_secret())


def test_username_unique_under_concurrency(tmp_path: Path):
    store = _store(tmp_path)
    owner, _ = _bootstrap(store)
    results = []
    errors = []
    def worker():
        try:
            results.append(store.create_user(actor=owner, username="same", password="LongTraderPassword1!", role=UserRole.TRADER, require_mfa=False))
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(results) == 1
    assert len(errors) == 1


def test_private_app_service_has_no_execution_imports():
    source = Path("atlas/api/app_service.py").read_text(encoding="utf-8")
    forbidden = ["demo_transport", "trade_management", "mt5_bridge", "order_send", "ControlledDemoExecutionGate"]
    assert all(x not in source for x in forbidden)
