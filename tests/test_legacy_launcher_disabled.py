import run_live_dashboard

def test_legacy_dashboard_is_hard_disabled():
    assert run_live_dashboard.main() == 2
