from __future__ import annotations

import json
from pathlib import Path

from atlas.api import AtlasPrivateAppService, AtlasReadModelService
from atlas.security import SQLiteAuthStore, TOTP, UserRole
from atlas.staging import LeadStore


def _bootstrap(tmp_path: Path):
    auth = SQLiteAuthStore(tmp_path / "auth.sqlite3")
    secret = TOTP.generate_secret()
    owner = auth.create_user(actor=None, username="owner", password="CorrectHorseBattery1!", role=UserRole.OWNER, mfa_secret=secret)
    read = AtlasReadModelService(dashboard_path=tmp_path / "dashboard_state.json", execution_db=tmp_path / "exec.sqlite3")
    app = AtlasPrivateAppService(auth=auth, leads=LeadStore(tmp_path / "leads.jsonl"), read_models=read)
    return auth, owner, app


def test_ui_assets_and_login_are_real_files():
    for name in ["web/public/app/index.html", "web/public/app/login.html", "web/public/app/app.css", "web/public/app/app.js"]:
        assert Path(name).exists(), name
    assert "Client Login" in Path("web/public/app/login.html").read_text(encoding="utf-8")
    assert "REAL MONEY DISABLED" in Path("web/public/app/index.html").read_text(encoding="utf-8")


def test_web_api_boundary_has_no_mt5_execution_imports():
    source = Path("atlas/api/app_service.py").read_text(encoding="utf-8") + Path("atlas/api/read_models.py").read_text(encoding="utf-8")
    forbidden = ["order_send", "DemoOnlyMT5Transport", "ControlledDemoExecutionGate", "mt5_bridge"]
    assert all(x not in source for x in forbidden)


def test_read_model_watchlist_and_role_filtered_accounts(tmp_path: Path):
    auth, owner, app = _bootstrap(tmp_path)
    trader = auth.create_user(actor=owner, username="trader", password="LongTraderPassword1!", role=UserRole.TRADER, account_ids=["A1", "A2"], require_mfa=False)
    dashboard = {
        "mode": "READ_ONLY_OBSERVATION", "execution_enabled": False,
        "watchlist": [{"symbol": "EURUSD", "h4_trend": "BULLISH", "supervisor": "WAIT"}],
        "account": {"account_id": "A1", "balance": 100000}, "open_positions": [], "summary": {"symbols": 1},
    }
    (tmp_path / "dashboard_state.json").write_text(json.dumps(dashboard), encoding="utf-8")
    rows = app.list_account_summaries(trader)
    assert [x["account_id"] for x in rows] == ["A1", "A2"]
    assert rows[0]["connected_snapshot"]["balance"] == 100000
    assert rows[1]["connected_snapshot"] is None
    assert app.watchlist(trader)[0]["symbol"] == "EURUSD"


def test_owner_dashboard_and_user_listing(tmp_path: Path):
    auth, owner, app = _bootstrap(tmp_path)
    app.create_user(owner, username="trader", password="LongTraderPassword1!", role="TRADER", account_ids=["D1"])
    users = app.list_users(owner)
    assert {u["role"] for u in users} == {"OWNER", "TRADER"}
    dashboard = app.dashboard(owner)
    assert dashboard["managed_account_count"] == 1
