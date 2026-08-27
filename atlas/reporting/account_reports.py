from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

SENSITIVE_KEYS = {
    "owner_name", "account_name", "login", "account_login", "email", "phone",
    "server", "broker_account_number", "password", "address"
}

@dataclass(frozen=True, slots=True)
class AccountReport:
    account_id: str
    summary: dict[str, Any]
    trades: tuple[dict[str, Any], ...]

class AccountReportBuilder:
    """Creates strictly separated per-account reports from account-tagged journals."""
    def build_all(self, records: Iterable[dict[str, Any]]) -> dict[str, AccountReport]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for raw in records:
            account_id = str(raw.get("account_id") or "").strip()
            if not account_id:
                raise ValueError("every report record must contain account_id")
            grouped[account_id].append(dict(raw))
        return {aid: self._build(aid, rows) for aid, rows in grouped.items()}

    def _build(self, account_id: str, rows: list[dict[str, Any]]) -> AccountReport:
        resolved = [r for r in rows if r.get("r_result") is not None]
        r_values = [float(r["r_result"]) for r in resolved]
        wins = sum(1 for r in r_values if r > 0)
        losses = sum(1 for r in r_values if r < 0)
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        max_w = max_l = cur_w = cur_l = 0
        pattern_r: dict[str, float] = defaultdict(float)
        for row, r in zip(resolved, r_values):
            equity += r
            peak = max(peak, equity)
            max_dd = max(max_dd, peak - equity)
            if r > 0:
                cur_w += 1; cur_l = 0; max_w = max(max_w, cur_w)
            elif r < 0:
                cur_l += 1; cur_w = 0; max_l = max(max_l, cur_l)
            pattern_r[str(row.get("pattern") or "UNKNOWN")] += r
        gross_win = sum(r for r in r_values if r > 0)
        gross_loss = -sum(r for r in r_values if r < 0)
        summary = {
            "trades": len(rows), "resolved": len(resolved), "wins": wins, "losses": losses,
            "win_rate": wins / len(resolved) if resolved else 0.0,
            "net_r": sum(r_values), "expectancy_r": sum(r_values) / len(resolved) if resolved else 0.0,
            "profit_factor": (gross_win / gross_loss) if gross_loss else (float("inf") if gross_win else 0.0),
            "max_drawdown_r": max_dd, "max_consecutive_wins": max_w, "max_consecutive_losses": max_l,
            "pattern_net_r": dict(sorted(pattern_r.items())),
        }
        return AccountReport(account_id, summary, tuple(rows))

class TrainingReportBuilder:
    """Produces owner/account-neutral training data with no account identifiers."""
    def build(self, reports: dict[str, AccountReport]) -> dict[str, Any]:
        aggregate_records: list[dict[str, Any]] = []
        for report in reports.values():
            for row in report.trades:
                clean = {k: v for k, v in row.items() if k not in SENSITIVE_KEYS and k != "account_id"}
                aggregate_records.append(clean)
        resolved = [r for r in aggregate_records if r.get("r_result") is not None]
        vals = [float(r["r_result"]) for r in resolved]
        return {
            "mode": "TRAINING_ANONYMIZED",
            "account_count": len(reports),
            "trades": len(aggregate_records),
            "resolved": len(resolved),
            "wins": sum(v > 0 for v in vals),
            "losses": sum(v < 0 for v in vals),
            "net_r": sum(vals),
            "records": aggregate_records,
        }
