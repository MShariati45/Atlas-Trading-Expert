from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import json

from atlas.market_data.live_runtime import ReadOnlyAtlasRuntime, RuntimeSnapshot
from atlas.market_data.mt5_feed import MT5MarketDataFeed
from atlas.market_data.m15_live_runtime import M15LiveSpecialistRuntime
from atlas.services.paper_pipeline import LivePaperSupervisorPipeline
from atlas.services.h4_human_approval import H4HumanApprovalStore


@dataclass(slots=True)
class WatchSymbolView:
    symbol: str
    bid: float | None
    ask: float | None
    spread_points: float | None
    h4_trend: str
    h4_phase: str
    h4_effective_direction: str
    h4_trendline_state: str
    h4_trendline_touches: int
    h4_trendline_quality: str
    h1_trend: str
    h1_phase: str
    alignment: str
    fib_pct: float | None
    fib_zone: str
    flag_pennant: str
    broad_m15: str
    coordinator: str
    supervisor: str
    supervisor_reason: str
    last_h4_bar: str | None
    last_h1_bar: str | None
    changed: bool
    error: str | None = None
    m15_reports: list[dict[str, Any]] | None = None
    opportunity_package: dict[str, Any] | None = None
    paper_review: dict[str, Any] | None = None
    h4_human_approval: dict[str, Any] | None = None


class LiveObservationDashboardService:
    """Builds read-only multi-symbol dashboard state from persisted Atlas runtime.

    This service never sends orders. It deliberately distinguishes unavailable
    live services from clear/approved states so the UI cannot imply safety data
    exists when no live news/static-zone provider has been configured yet.
    """

    def __init__(self, feed: MT5MarketDataFeed, runtime: ReadOnlyAtlasRuntime, out_path: str | Path, m15_runtime: M15LiveSpecialistRuntime | None = None, paper_pipeline: LivePaperSupervisorPipeline | None = None) -> None:
        self.feed = feed
        self.runtime = runtime
        self.m15_runtime = m15_runtime
        self.paper_pipeline = paper_pipeline
        self.out_path = Path(out_path)
        self.h4_approvals = H4HumanApprovalStore(self.out_path.parent.parent / "runtime" / "h4_human_approvals.json")
        self._fingerprints: dict[str, tuple[Any, ...]] = {}

    @staticmethod
    def _alignment(snap: RuntimeSnapshot) -> str:
        report = snap.alignment or {}
        return "ALIGNED" if report.get("aligned") is True else str(report.get("state") or "UNKNOWN")

    @staticmethod
    def _fingerprint(snap: RuntimeSnapshot) -> tuple[Any, ...]:
        fib = snap.fibonacci or {}
        return (
            snap.h4.get("trend"), snap.h4.get("phase"), snap.h4.get("effective_direction"), snap.h4.get("trendline", {}).get("status"), snap.h4.get("state_version"),
            snap.h1.get("trend"), snap.h1.get("phase"), snap.h1.get("state_version"),
            fib.get("zone"), round(float(fib.get("retracement_pct", -1.0)), 3) if fib else None,
            snap.last_h4_bar, snap.last_h1_bar,
        )

    def _symbol_view(self, symbol: str) -> WatchSymbolView:
        try:
            snap = self.runtime.poll_symbol(symbol)
            tick = self.feed.tick(symbol)
            meta = self.feed.ensure_symbol(symbol)
            fib = snap.fibonacci or {}
            alignment = self._alignment(snap)
            fib_pct = float(fib["retracement_pct"]) if "retracement_pct" in fib else None
            fib_zone = str(fib.get("zone", "INACTIVE"))
            flag_active = bool(fib.get("flag_early_access", False))
            broad_active = bool(fib.get("broad_m15_activation", False))
            if alignment != "ALIGNED":
                flag_state = "SLEEP"
                broad_state = "SLEEP"
                reason = "H4/H1 not aligned; downstream opportunity agents sleeping."
            elif flag_active:
                flag_state = "SCANNING"
                broad_state = "SLEEP"
                reason = "Shallow H1 correction; Flag/Pennant has early access."
            elif broad_active:
                flag_state = "NO_NEW_DISCOVERY"
                broad_state = "SCANNING"
                reason = "H1 retracement reached 38.2%+; broad M15 specialist layer eligible."
            else:
                flag_state = "SLEEP"
                broad_state = "WAITING"
                reason = "Higher-timeframe alignment exists; waiting for an eligible correction state."
            coordinator = "WAITING_FOR_M15_REPORTS" if broad_active or flag_active else "IDLE"
            supervisor = "WAIT"
            m15_reports = None
            opportunity_package = None
            paper_review = None
            if self.m15_runtime is not None and alignment == "ALIGNED" and fib_pct is not None and (broad_active or flag_active):
                direction = "LONG" if str(snap.h1.get("trend")) == "BULLISH" else "SHORT"
                m15 = self.m15_runtime.poll(
                    symbol,
                    direction,
                    fib_pct,
                    broad_m15_activation=broad_active,
                    new_flag_discovery_allowed=bool(fib.get("new_flag_discovery_allowed", flag_active)),
                    structure_risk=str(fib.get("state", "")).upper() == "STRUCTURE_RISK",
                )
                m15_reports = m15.reports
                opportunity_package = m15.coordinator
                coordinator = str(m15.coordinator.get("coordination_state", coordinator))
                if coordinator == "READY_FOR_SUPERVISOR_REVIEW":
                    supervisor = "PAPER_REVIEW_READY"
                    reason = "Real completed M15 bars produced an actionable package; execution remains disabled."
                    if self.paper_pipeline is not None:
                        paper = self.paper_pipeline.review(symbol=symbol, direction=direction, package=opportunity_package, alignment_ok=True, fib_ok=True)
                        paper_review = paper.to_dict()
                        supervisor = f"PAPER_{paper.decision}"
                        reason = ", ".join(paper.reason_codes[:4]) or "Paper Supervisor review complete."
            fp = self._fingerprint(snap)
            changed = self._fingerprints.get(symbol) != fp
            self._fingerprints[symbol] = fp
            point = meta.point if meta.point > 0 else 1.0
            spread_points = tick.spread_price / point
            human_approval = self.h4_approvals.dashboard_state(symbol, snap.h4)
            return WatchSymbolView(
                symbol=symbol,
                bid=tick.bid,
                ask=tick.ask,
                spread_points=spread_points,
                h4_trend=str(snap.h4.get("trend", "UNKNOWN")),
                h4_phase=str(snap.h4.get("phase", "UNKNOWN")),
                h4_effective_direction=str(
    human_approval.get("approved_trend")
    if human_approval.get("execution_authorized_directionally")
    else snap.h4.get("effective_direction", snap.h4.get("trend", "UNKNOWN"))
),
                h4_trendline_state=str((snap.h4.get("trendline") or {}).get("status", "UNAVAILABLE")),
                h4_trendline_touches=int((snap.h4.get("trendline") or {}).get("touch_count", 0) or 0),
                h4_trendline_quality=str((snap.h4.get("trendline") or {}).get("quality", "NONE")),
                h1_trend=str(snap.h1.get("trend", "UNKNOWN")),
                h1_phase=str(snap.h1.get("phase", "UNKNOWN")),
                alignment=alignment,
                fib_pct=fib_pct,
                fib_zone=fib_zone,
                flag_pennant=flag_state,
                broad_m15=broad_state,
                coordinator=coordinator,
                supervisor=supervisor,
                supervisor_reason=reason,
                last_h4_bar=snap.last_h4_bar,
                last_h1_bar=snap.last_h1_bar,
                changed=changed, m15_reports=m15_reports, opportunity_package=opportunity_package, paper_review=paper_review, h4_human_approval=human_approval,
            )
        except Exception as exc:
            return WatchSymbolView(
                symbol=symbol, bid=None, ask=None, spread_points=None,
                h4_trend="ERROR", h4_phase="ERROR", h4_effective_direction="ERROR", h4_trendline_state="ERROR", h4_trendline_touches=0, h4_trendline_quality="NONE", h1_trend="ERROR", h1_phase="ERROR",
                alignment="UNKNOWN", fib_pct=None, fib_zone="UNAVAILABLE",
                flag_pennant="SLEEP", broad_m15="SLEEP", coordinator="IDLE",
                supervisor="WAIT", supervisor_reason="Live observation error; no decision allowed.",
                last_h4_bar=None, last_h1_bar=None, changed=True, error=str(exc), m15_reports=None, opportunity_package=None, paper_review=None,
            )

    def build(self, symbols: Iterable[str]) -> dict[str, Any]:
        account: dict[str, Any]
        positions: list[dict[str, Any]]
        terminal: dict[str, Any]
        try:
            account = self.feed.snapshot_dict(self.feed.account_snapshot())
            positions = self.feed.positions()
            terminal = self.feed.terminal_health()
        except Exception as exc:
            account = {"status": "UNAVAILABLE", "error": str(exc)}
            positions = []
            terminal = {"terminal_connected": False, "error": str(exc)}

        views = [self._symbol_view(s) for s in symbols]
        changed_count = sum(1 for v in views if v.changed)
        errors = [v.symbol for v in views if v.error]
        return {
            "schema_version": "1.0",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "mode": "READ_ONLY_OBSERVATION",
            "execution_enabled": False,
            "terminal": terminal,
            "account": account,
            "open_positions": positions,
            "watchlist": [asdict(v) for v in views],
            "summary": {
                "symbols": len(views),
                "changed": changed_count,
                "errors": errors,
                "open_positions": len(positions),
                "news_guard": "LIVE_OR_PENDING" if self.paper_pipeline is not None else "NOT_CONFIGURED_LIVE",
                "static_zones": "LIVE_CACHED" if self.paper_pipeline is not None else "NOT_CONFIGURED_LIVE",
                "api_mode": "EVENT_DRIVEN_PERSISTED_STATE",
            },
        }

    def write(self, symbols: Iterable[str]) -> dict[str, Any]:
        state = self.build(symbols)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.out_path.with_suffix(self.out_path.suffix + ".tmp")
        temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temp.replace(self.out_path)
        return state
