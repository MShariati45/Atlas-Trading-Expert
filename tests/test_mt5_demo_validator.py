from datetime import datetime, timezone

from atlas.execution.demo_validator import MT5DemoValidator
from atlas.execution.models import AccountConfig
from tests.test_mt5_market_data import feed_with_fake


def test_demo_validator_is_read_only_and_ready_for_observation():
    feed = feed_with_fake()
    now = datetime.fromtimestamp(1_700_000_000 + 20 * 60, tz=timezone.utc)
    report = MT5DemoValidator(feed).validate(
        AccountConfig("DEMO", True, 0.5),
        ["EURUSD"],
        now=now,
        history_requirements={"D1": 10, "H4": 10, "H1": 10, "M15": 10},
        max_age_seconds={"D1": 999999, "H4": 999999, "H1": 999999, "M15": 999999},
        max_tick_age_seconds=999999,
    )
    assert report.ready_for_observation is True
    assert report.ready_for_paper_supervision is False  # live news intentionally not configured
    assert report.execution_enabled is False
    assert report.execution_locked is True
    assert report.symbols["EURUSD"].history_ok is True


def test_demo_validator_rejects_wrong_expected_account():
    feed = feed_with_fake()
    now = datetime.fromtimestamp(1_700_000_000 + 20 * 60, tz=timezone.utc)
    report = MT5DemoValidator(feed).validate(
        AccountConfig("DEMO", True, 0.5), ["EURUSD"], now=now, expected_login=999,
        history_requirements={"M15": 10}, max_age_seconds={"M15": 999999}, max_tick_age_seconds=999999,
    )
    assert report.expected_account_match is False
    assert report.ready_for_observation is False
    assert any("ACCOUNT_LOGIN_MISMATCH" in x for x in report.notes)
