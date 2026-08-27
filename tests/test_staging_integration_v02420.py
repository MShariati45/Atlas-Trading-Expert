from pathlib import Path

from atlas.security import AccessPolicy, UserIdentity, UserRole
from atlas.staging import LeadStore, StagingReadiness, StagingUserService


def test_public_lead_submission_is_stored_without_creating_user(tmp_path):
    store = LeadStore(tmp_path / "leads.jsonl")
    lead = store.submit(name="Test Lead", email="lead@example.com", country="Canada", message="Private beta")
    rows = store.list_all()
    assert len(rows) == 1
    assert rows[0].lead_id == lead.lead_id
    assert rows[0].email == "lead@example.com"
    assert rows[0].status.value == "NEW"


def test_staging_role_model_owner_admin_trader():
    owner = UserIdentity("O", "owner", UserRole.OWNER)
    admin = UserIdentity("A", "admin", UserRole.ADMIN)
    trader = UserIdentity("T", "trader", UserRole.TRADER, frozenset({"ACC-1"}))
    assert StagingUserService.can_create_user(owner)
    assert not StagingUserService.can_create_user(admin)
    assert AccessPolicy.can_view_account(trader, "ACC-1")
    assert not AccessPolicy.can_control_account(trader, "ACC-1")
    assert AccessPolicy.can_modify_strategy(admin)


def test_staging_readiness_fails_closed_without_news_runtime(tmp_path):
    (tmp_path / "web/public").mkdir(parents=True)
    (tmp_path / "web/public/index.html").write_text("ok")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/leads.jsonl").touch()
    (tmp_path / "atlas/security").mkdir(parents=True)
    (tmp_path / "atlas/security/access_control.py").write_text("ok")
    (tmp_path / "atlas/services").mkdir(parents=True)
    (tmp_path / "atlas/services/h4_human_approval.py").write_text("ok")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/broker_cost_policy.json").write_text("{}")
    report = StagingReadiness.inspect(tmp_path)
    assert report.code_ready
    assert not report.market_open_ready
    assert report.demo_execution_locked


def test_staging_readiness_rejects_stale_news_file(tmp_path):
    import json
    from datetime import datetime, timezone
    (tmp_path / "web/public").mkdir(parents=True)
    (tmp_path / "web/public/index.html").write_text("ok")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/leads.jsonl").touch()
    (tmp_path / "atlas/security").mkdir(parents=True)
    (tmp_path / "atlas/security/access_control.py").write_text("ok")
    (tmp_path / "atlas/services").mkdir(parents=True)
    (tmp_path / "atlas/services/h4_human_approval.py").write_text("ok")
    (tmp_path / "config").mkdir()
    (tmp_path / "config/broker_cost_policy.json").write_text("{}")
    payload = {
        "generated_at_utc": "2026-08-20T00:00:00+00:00",
        "valid_until_utc": "2026-08-20T12:00:00+00:00",
        "source_name": "test",
        "source_url": "https://example.invalid",
        "coverage_currencies": ["USD", "EUR", "CAD", "JPY"],
        "events": [],
    }
    (tmp_path / "runtime/news_events.json").write_text(json.dumps(payload))
    report = StagingReadiness.inspect(tmp_path, datetime(2026, 8, 22, tzinfo=timezone.utc))
    assert report.news_runtime_present
    assert not report.news_runtime_valid
    assert not report.market_open_ready
    assert report.news_runtime_error == "LIVE_NEWS_SCHEDULE_STALE_OR_TOO_SHORT"
