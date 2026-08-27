from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json

VALID_TRENDS = {"BULLISH", "BEARISH", "RANGE", "TRANSITION"}


def _utc(value: str) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(slots=True)
class H4Approval:
    symbol: str
    trend: str
    impulse_start: float | None
    impulse_end: float | None
    approved_at_utc: str
    expires_at_utc: str | None = None
    structure_token: str | None = None
    source: str = "HUMAN"
    note: str = ""

    @property
    def directional(self) -> bool:
        return self.trend in {"BULLISH", "BEARISH"}


class H4HumanApprovalStore:
    """Local authoritative H4 approval with explicit staleness control.

    Directional approvals expire by default after 24 hours. A caller may also
    supply a structure_token at approval and execution time; a mismatch forces
    human review immediately. This keeps the owner's checkpoint authoritative
    without allowing an old approval to live forever.
    """
    def __init__(self, path: str | Path = "runtime/h4_human_approvals.json", *, max_age_hours: float = 24.0) -> None:
        self.path = Path(path)
        self.max_age = timedelta(hours=float(max_age_hours))

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": "1.1", "approvals": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def approve(self, symbol: str, trend: str, impulse_start: float | None = None,
                impulse_end: float | None = None, note: str = "", *,
                structure_token: str | None = None, now: datetime | None = None,
                expires_at_utc: str | None = None) -> H4Approval:
        symbol = symbol.upper().strip()
        trend = trend.upper().strip()
        if trend not in VALID_TRENDS:
            raise ValueError(f"trend must be one of {sorted(VALID_TRENDS)}")
        if trend in {"BULLISH", "BEARISH"} and (impulse_start is None or impulse_end is None):
            raise ValueError("directional approval requires impulse_start and impulse_end")
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expires = expires_at_utc or (now + self.max_age).isoformat()
        a = H4Approval(symbol, trend, impulse_start, impulse_end, now.isoformat(), expires,
                       structure_token, "HUMAN", note)
        data = self._read()
        data["schema_version"] = "1.1"
        data.setdefault("approvals", {})[symbol] = asdict(a)
        self._write(data)
        return a

    def revoke(self, symbol: str) -> None:
        data = self._read()
        data.setdefault("approvals", {}).pop(symbol.upper().strip(), None)
        self._write(data)

    def get(self, symbol: str) -> H4Approval | None:
        row = self._read().get("approvals", {}).get(symbol.upper().strip())
        if not row:
            return None
        row = dict(row)
        row.setdefault("expires_at_utc", None)
        row.setdefault("structure_token", None)
        return H4Approval(**row)

    def execution_gate(self, symbol: str, direction: str | None = None, *,
                       now: datetime | None = None, current_structure_token: str | None = None) -> tuple[bool, str]:
        a = self.get(symbol)
        if a is None:
            return False, "H4_HUMAN_APPROVAL_REQUIRED"
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        expiry = _utc(a.expires_at_utc) if a.expires_at_utc else _utc(a.approved_at_utc) + self.max_age
        if now >= expiry:
            return False, "H4_HUMAN_APPROVAL_STALE"
        if a.structure_token and current_structure_token and a.structure_token != current_structure_token:
            return False, "H4_STRUCTURE_CHANGED_REVIEW_REQUIRED"
        if not a.directional:
            return False, f"H4_HUMAN_STATE_{a.trend}_BLOCKS_DIRECTIONAL_ENTRY"
        if direction:
            wanted = "BULLISH" if direction.upper() == "LONG" else "BEARISH"
            if a.trend != wanted:
                return False, "TRADE_DIRECTION_CONFLICTS_WITH_H4_HUMAN_APPROVAL"
        return True, "H4_HUMAN_APPROVAL_OK"

    def dashboard_state(self, symbol: str, atlas_prediction: dict[str, Any] | None = None,
                        *, now: datetime | None = None) -> dict[str, Any]:
        a = self.get(symbol)
        pred = atlas_prediction or {}
        atlas_trend = str(pred.get("trend", "UNKNOWN")).upper()
        stale = False
        if a:
            check_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            expiry = _utc(a.expires_at_utc) if a.expires_at_utc else _utc(a.approved_at_utc) + self.max_age
            stale = check_now >= expiry
        return {
            "required": True,
            "status": "REVIEW_REQUIRED" if not a or stale else "APPROVED",
            "approved_trend": a.trend if a else None,
            "impulse_start": a.impulse_start if a else None,
            "impulse_end": a.impulse_end if a else None,
            "approved_at_utc": a.approved_at_utc if a else None,
            "expires_at_utc": a.expires_at_utc if a else None,
            "stale": stale,
            "note": a.note if a else "",
            "atlas_trend": atlas_trend,
            "agrees_with_atlas": (a.trend == atlas_trend) if a and atlas_trend != "UNKNOWN" else None,
            "execution_authorized_directionally": bool(a and a.directional and not stale),
            "api_calls": 0,
        }
