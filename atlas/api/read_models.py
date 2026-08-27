from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from atlas.execution.sqlite_execution_ledger import SQLiteExecutionLedger
from atlas.security import AccessPolicy, UserIdentity, UserRole


class AtlasReadModelService:
    """Read-only adapter used by the authenticated web application.

    It deliberately reads persisted Atlas state and the execution ledger only.
    There are no MT5 bridge/order imports in this module.
    """

    def __init__(self, *, dashboard_path: str | Path = "runtime/dashboard_state.json",
                 execution_db: str | Path = "runtime/demo_execution.sqlite3") -> None:
        self.dashboard_path = Path(dashboard_path)
        self.ledger = SQLiteExecutionLedger(execution_db)

    def dashboard_state(self) -> dict[str, Any]:
        if not self.dashboard_path.exists():
            return {
                "schema_version": "1.0", "generated_at_utc": None,
                "mode": "STAGING_NO_LIVE_SNAPSHOT", "execution_enabled": False,
                "terminal": {"terminal_connected": False}, "account": {"status": "UNAVAILABLE"},
                "open_positions": [], "watchlist": [],
                "summary": {"symbols": 0, "changed": 0, "errors": [], "open_positions": 0,
                            "news_guard": "UNKNOWN", "static_zones": "UNKNOWN", "api_mode": "PERSISTED_READ_MODEL"},
            }
        try:
            raw = json.loads(self.dashboard_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {"error": "invalid dashboard state"}
        except Exception:
            return {"error": "dashboard state unavailable", "watchlist": [], "open_positions": [],
                    "summary": {"symbols": 0, "errors": ["DASHBOARD_STATE"]}, "execution_enabled": False}

    def watchlist(self) -> list[dict[str, Any]]:
        rows = self.dashboard_state().get("watchlist", [])
        return [dict(x) for x in rows if isinstance(x, dict)]

    def account_summary(self, actor: UserIdentity, account_id: str) -> dict[str, Any]:
        if not AccessPolicy.can_view_account(actor, account_id):
            raise PermissionError("account access denied")
        state = self.dashboard_state()
        current = state.get("account", {}) if isinstance(state.get("account"), dict) else {}
        positions = [p for p in state.get("open_positions", []) if isinstance(p, dict)]
        # Current dashboard snapshot represents the locally connected terminal. It is included
        # only when its account id/login can be associated with the requested account.
        login = str(current.get("login") or current.get("account_id") or "")
        connected_match = login == str(account_id) or str(current.get("account_id") or "") == str(account_id)
        if actor.role in {UserRole.OWNER, UserRole.ADMIN} and not login:
            connected_match = False
        exec_rows = self._execution_rows(account_id, limit=200)
        return {
            "account_id": account_id,
            "read_only": actor.role is UserRole.TRADER,
            "connected_snapshot": current if connected_match else None,
            "demo_verified": bool(current.get("demo_verified", False)) if connected_match else False,
            "open_positions": positions if connected_match else [],
            "executions": exec_rows,
            "execution_count": len(exec_rows),
            "last_activity_utc": exec_rows[0]["prepared_at_utc"] if exec_rows else None,
        }

    def _execution_rows(self, account_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        with self.ledger._connect() as con:  # read-only query over the ledger's own connection policy
            rows = con.execute(
                """SELECT signal_id,ticket_id,symbol,risk_pct,status,prepared_at_utc,details_json,updated_at
                   FROM execution_claims WHERE account_id=? ORDER BY prepared_at_utc DESC LIMIT ?""",
                (account_id, int(limit)),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            details = json.loads(r[6] or "{}")
            safe_details = {k: v for k, v in details.items() if k not in {"password", "token", "secret"}}
            out.append({
                "account_id": account_id, "signal_id": r[0], "ticket_id": r[1], "symbol": r[2],
                "risk_pct": float(r[3]), "status": r[4], "prepared_at_utc": r[5],
                "details": safe_details, "updated_at": r[7],
            })
        return out

    def owner_dashboard(self, actor: UserIdentity, account_ids: list[str]) -> dict[str, Any]:
        if actor.role not in {UserRole.OWNER, UserRole.ADMIN}:
            raise PermissionError("owner/admin role required")
        state = self.dashboard_state()
        watchlist = self.watchlist()
        by_symbol: dict[str, dict[str, Any]] = {}
        for row in watchlist:
            sym = str(row.get("symbol") or "UNKNOWN")
            by_symbol[sym] = {
                "symbol": sym,
                "h4": row.get("h4_effective_direction") or row.get("h4_trend"),
                "alignment": row.get("alignment"), "supervisor": row.get("supervisor"),
                "spread_points": row.get("spread_points"), "human": row.get("h4_human_approval"),
            }
        return {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "runtime_generated_at_utc": state.get("generated_at_utc"),
            "mode": state.get("mode", "STAGING"), "execution_enabled": bool(state.get("execution_enabled", False)),
            "terminal": state.get("terminal", {}), "account": state.get("account", {}),
            "open_positions": state.get("open_positions", []), "summary": state.get("summary", {}),
            "symbol_health": list(by_symbol.values()), "managed_account_count": len(set(account_ids)),
        }
