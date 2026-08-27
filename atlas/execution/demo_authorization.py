from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json, os
from atlas.execution.models import AccountConfig, ApprovedSignal
from atlas.risk.policy import RiskPolicy
from atlas.services.h4_human_approval import H4HumanApprovalStore
from atlas.execution.account_identity import AccountIdentityVerifier

@dataclass(slots=True)
class DemoAuthorizationDecision:
    allowed: bool
    mode: str
    reasons: list[str]
    risk_pct: float
    max_trades_per_day: int
    max_trades_per_symbol_per_day: int
    checked_at_utc: str
    def to_dict(self): return asdict(self)

class DemoExecutionAuthorizer:
    """Fail-closed authorization gate before any MT5 demo mutation.

    This is deterministic/local and performs zero AI/API calls. LIVE accounts are
    categorically forbidden. Demo execution additionally requires an explicit local
    enable file + environment acknowledgement, human H4 approval, risk limits, and
    a passing preflight report.
    """
    def __init__(self, *, approval_store: H4HumanApprovalStore | None = None,
                 enable_file: str | Path = "runtime/DEMO_EXECUTION_ENABLE.json",
                 preflight_file: str | Path = "runtime/demo_preflight_report.json",
                 risk_policy: RiskPolicy | None = None, identity_verifier: AccountIdentityVerifier | None = None) -> None:
        self.approvals = approval_store or H4HumanApprovalStore()
        self.enable_file = Path(enable_file)
        self.preflight_file = Path(preflight_file)
        self.risk = risk_policy or RiskPolicy()
        self.identity = identity_verifier or AccountIdentityVerifier()

    def _enabled(self) -> bool:
        if os.getenv("ATLAS_DEMO_EXECUTION", "").upper() != "YES": return False
        if not self.enable_file.exists(): return False
        try:
            d=json.loads(self.enable_file.read_text(encoding="utf-8"))
            return d.get("mode") == "DEMO_ONLY" and d.get("enabled") is True
        except Exception: return False

    def authorize(self, account: AccountConfig, signal: ApprovedSignal, *,
                  trades_today: int, symbol_trades_today: int,
                  daily_risk_used_pct: float, open_symbol_position: bool,
                  now: datetime | None = None) -> DemoAuthorizationDecision:
        reasons=[]
        pf={}
        if self.preflight_file.exists():
            try: pf=json.loads(self.preflight_file.read_text(encoding="utf-8"))
            except Exception: reasons.append("PREFLIGHT_REPORT_INVALID")
        else: reasons.append("PREFLIGHT_REPORT_MISSING")
        if pf and not bool(pf.get("ready_for_paper_supervision", False)): reasons.append("PREFLIGHT_NOT_READY")
        identity = self.identity.from_preflight(account, pf)
        if not identity.demo_verified: reasons.append("LIVE_OR_UNVERIFIED_ACCOUNT_FORBIDDEN")
        if not self._enabled(): reasons.append("DEMO_EXECUTION_NOT_EXPLICITLY_ENABLED")
        ok, why=self.approvals.execution_gate(signal.symbol, signal.direction, now=now)
        if not ok: reasons.append(why)
        if account.risk_pct > self.risk.default_risk_per_trade_pct + 1e-12: reasons.append("RISK_PER_TRADE_EXCEEDS_0_5_PERCENT")
        if trades_today >= self.risk.max_trades_per_day: reasons.append("DAILY_TRADE_LIMIT_REACHED")
        if symbol_trades_today >= self.risk.max_trades_per_symbol_per_day: reasons.append("SYMBOL_DAILY_TRADE_LIMIT_REACHED")
        if open_symbol_position: reasons.append("OPEN_POSITION_ALREADY_EXISTS_FOR_SYMBOL")
        if daily_risk_used_pct + account.risk_pct > self.risk.max_daily_risk_pct + 1e-12: reasons.append("DAILY_RISK_CAP_EXCEEDED")
        if signal.direction.upper() == "LONG" and not (signal.stop < signal.entry < signal.target): reasons.append("INVALID_LONG_PRICE_GEOMETRY")
        if signal.direction.upper() == "SHORT" and not (signal.target < signal.entry < signal.stop): reasons.append("INVALID_SHORT_PRICE_GEOMETRY")
        if signal.direction.upper() not in {"LONG","SHORT"}: reasons.append("INVALID_DIRECTION")
        return DemoAuthorizationDecision(not reasons, "DEMO_ONLY", reasons, account.risk_pct,
            self.risk.max_trades_per_day, self.risk.max_trades_per_symbol_per_day,
            (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat())
