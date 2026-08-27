"""Offline Atlas v0.24.22 staging invariant check. No MT5 or AI/API calls."""
from __future__ import annotations

import json
from pathlib import Path

from atlas.execution.mt5_bridge import MT5PythonBridge
from atlas.strategy.profile import ALL_PATTERNS, default_m15_first_profile
from atlas.governance.roles import ROLE_CONTRACTS
from atlas.research.trusted_sources import TRUSTED_SOURCES
from atlas.security import UserRole
from atlas.accounts import MultiTerminalAccountOrchestrator
from atlas.reporting import AccountReportBuilder, TrainingReportBuilder

EXPECTED = ("EURUSD", "USDJPY", "USDCAD", "XAUUSD")


def main() -> int:
    base = Path(__file__).resolve().parent
    cfg = json.loads((base / "config" / "atlas_m15_first_v0.24.4.json").read_text(encoding="utf-8"))
    profile = default_m15_first_profile()
    checks: list[tuple[str, bool]] = []
    checks.append(("watchlist_exact", profile.watchlist == EXPECTED == tuple(cfg["watchlist"])))
    checks.append(("gbpusd_absent", "GBPUSD" not in profile.watchlist and "GBPUSD" not in cfg["symbols"]))
    checks.append(("channel_breakout_absent", "CHANNEL_BREAKOUT" not in ALL_PATTERNS))
    checks.append(("boundary_rejection_present", "CHANNEL_BOUNDARY_REJECTION" in ALL_PATTERNS))
    checks.append(("fibonacci_gate_off", profile.fibonacci_enabled is False and cfg["hierarchy"]["fibonacci_permission_gate_enabled"] is False))
    checks.append(("risk_0_5_per_trade", profile.risk_per_trade_pct == 0.5))
    checks.append(("daily_risk_1_0", profile.max_daily_risk_pct == 1.0))
    checks.append(("two_trades_max", profile.max_trades_per_day == 2))
    checks.append(("one_symbol_trade_max", profile.max_trades_per_symbol_per_day == 1))
    checks.append(("ai_disabled", cfg["ai_usage"]["enabled"] is False))
    checks.append(("execution_bridge_locked", MT5PythonBridge().execution_enabled is False))
    checks.append(("role_contracts_present", {"H4_STRUCTURE","H1_STRUCTURE","M15_SPECIALISTS","M15_COORDINATOR","SUPERVISOR","RESEARCH_EDUCATION_SUPERVISOR"} <= set(ROLE_CONTRACTS)))
    checks.append(("trusted_sources_present", len(TRUSTED_SOURCES) >= 8 and all(x.url.startswith("https://") for x in TRUSTED_SOURCES)))
    checks.append(("research_cannot_mutate_live_rules", cfg.get("governance",{}).get("research_can_mutate_live_rules") is False))
    checks.append(("multi_account_worker_isolation", cfg.get("multi_account",{}).get("worker_isolation") == "ONE_PROCESS_PER_TERMINAL_ACCOUNT"))
    checks.append(("per_account_reporting_enabled", cfg.get("multi_account",{}).get("per_account_reporting") is True))
    checks.append(("access_roles_present", {"OWNER","ADMIN","TRADER"} == {r.value for r in UserRole}))
    checks.append(("training_anonymization_enabled", cfg.get("multi_account",{}).get("training_view_anonymized") is True))
    checks.append(("internet_login_server_still_off", cfg.get("multi_account",{}).get("internet_login_server_enabled") is False))
    checks.append(("demo_symbol_mapping_supported", cfg.get("demo_readiness",{}).get("broker_symbol_mapping_supported") is True))
    checks.append(("paper_requires_live_news", cfg.get("demo_readiness",{}).get("live_news_required_for_paper_supervision") is True))
    checks.append(("spread_slippage_calibration_required", cfg.get("demo_readiness",{}).get("spread_slippage_calibration_required_before_execution") is True))

    checks.append(("broker_spread_collector_present", (base / "run_mt5_broker_calibration.py").exists()))
    checks.append(("live_news_refresh_present", (base / "run_live_news_refresh.py").exists()))
    checks.append(("official_bls_news_refresh_present", (base / "run_official_us_news_refresh.py").exists()))
    checks.append(("official_four_currency_news_refresh_present", (base / "run_official_four_currency_news_refresh.py").exists() and (base / "run_official_four_currency_news_refresh.bat").exists()))
    checks.append(("news_currency_mapping_present", (base / "atlas" / "services" / "news_mapping.py").exists()))
    checks.append(("news_strict_coverage_documented", (base / "docs" / "NEWS_FAMILY_COVERAGE_AUDIT_v0.24.4.md").exists()))
    checks.append(("paper_requires_approved_cost_policy", cfg["demo_readiness"].get("spread_slippage_calibration_required_before_execution") is True))
    checks.append(("shadow_paper_supervisor_present", (base / "run_shadow_paper_supervisor.py").exists() and (base / "run_shadow_paper_supervisor.bat").exists()))
    checks.append(("shadow_paper_execution_off", cfg.get("demo_readiness",{}).get("shadow_paper_execution_enabled") is False))
    checks.append(("cost_policy_explicit_approval_required", cfg.get("demo_readiness",{}).get("broker_cost_policy_requires_explicit_approval") is True))
    checks.append(("paper_cost_policy_present", (base / "config" / "broker_cost_policy.json").exists()))
    checks.append(("paper_cost_policy_approved", cfg.get("demo_readiness",{}).get("paper_cost_policy_approved") is True))
    checks.append(("paper_cost_slippage_not_validated", cfg.get("demo_readiness",{}).get("paper_cost_slippage_validated") is False))
    checks.append(("nonpositive_spread_forces_wait", cfg.get("demo_readiness",{}).get("nonpositive_spread_forces_wait") is True))
    failed = [name for name, ok in checks if not ok]
    print(json.dumps({"atlas_version": "0.24.22", "checks": dict(checks), "passed": not failed, "failed": failed}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
