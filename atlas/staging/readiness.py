from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from atlas.services.news_mapping import currencies_for_symbols
from atlas.services.news_provider import JsonScheduledNewsProvider

WATCHLIST = ("EURUSD", "USDJPY", "USDCAD", "XAUUSD")
REQUIRED_CURRENCIES = currencies_for_symbols(WATCHLIST)


@dataclass(frozen=True, slots=True)
class StagingReadiness:
    landing_page: bool
    lead_store: bool
    role_model: bool
    h4_approval_gate: bool
    demo_execution_locked: bool
    news_runtime_present: bool
    news_runtime_valid: bool
    news_runtime_error: str | None
    broker_cost_policy_present: bool

    @property
    def code_ready(self) -> bool:
        return all([
            self.landing_page,
            self.lead_store,
            self.role_model,
            self.h4_approval_gate,
            self.demo_execution_locked,
            self.broker_cost_policy_present,
        ])

    @property
    def market_open_ready(self) -> bool:
        return self.code_ready and self.news_runtime_valid

    def to_dict(self) -> dict:
        return asdict(self) | {"code_ready": self.code_ready, "market_open_ready": self.market_open_ready}

    @classmethod
    def inspect(cls, root: str | Path = ".", now_utc: datetime | None = None) -> "StagingReadiness":
        root = Path(root)
        news_path = root / "runtime/news_events.json"
        news_present = news_path.exists()
        news_valid = False
        news_error: str | None = "LIVE_NEWS_RUNTIME_MISSING"
        if news_present:
            provider = JsonScheduledNewsProvider(
                news_path,
                strict_freshness=True,
                min_validity_seconds=6 * 3600,
                strict_provenance=True,
                required_currencies=REQUIRED_CURRENCIES,
            )
            provider.events((now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc))
            news_valid = provider.status.available
            news_error = provider.status.error
        return cls(
            landing_page=(root / "web/public/index.html").exists(),
            lead_store=(root / "runtime/leads.jsonl").exists(),
            role_model=(root / "atlas/security/access_control.py").exists(),
            h4_approval_gate=(root / "atlas/services/h4_human_approval.py").exists(),
            demo_execution_locked=not (root / "runtime/DEMO_EXECUTION_ENABLED").exists(),
            news_runtime_present=news_present,
            news_runtime_valid=news_valid,
            news_runtime_error=news_error,
            broker_cost_policy_present=(root / "config/broker_cost_policy.json").exists(),
        )
