from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


PAPER_ONLY = "PAPER_ONLY"
EXECUTION_VALIDATED = "EXECUTION_VALIDATED"
VALID_MODES = {PAPER_ONLY, EXECUTION_VALIDATED}


@dataclass(frozen=True, slots=True)
class BrokerCostPolicyStatus:
    approved: bool
    mode: str | None
    execution_validated: bool
    limits_by_symbol: dict[str, dict[str, Any]]
    reason_codes: tuple[str, ...]
    source_path: str


def load_broker_cost_policy(path: str | Path, required_symbols: tuple[str, ...]) -> BrokerCostPolicyStatus:
    """Load an explicitly approved Atlas broker-cost policy.

    PAPER_ONLY may use observed spread evidence while slippage remains unmeasured.
    EXECUTION_VALIDATED additionally requires measured/approved slippage assumptions.
    Neither mode can unlock MT5 order transmission; that remains a separate hard lock.
    """
    p = Path(path)
    if not p.exists():
        return BrokerCostPolicyStatus(False, None, False, {}, ("BROKER_COST_POLICY_MISSING",), str(p))
    try:
        raw: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return BrokerCostPolicyStatus(False, None, False, {}, ("BROKER_COST_POLICY_INVALID_JSON",), str(p))

    if raw.get("approved") is not True:
        return BrokerCostPolicyStatus(False, None, False, {}, ("BROKER_COST_POLICY_NOT_APPROVED",), str(p))

    mode = str(raw.get("mode") or "").upper()
    if mode not in VALID_MODES:
        return BrokerCostPolicyStatus(False, mode or None, False, {}, ("BROKER_COST_POLICY_MODE_INVALID",), str(p))

    execution_validated = bool(raw.get("execution_validated") is True)
    if mode == EXECUTION_VALIDATED and not execution_validated:
        return BrokerCostPolicyStatus(False, mode, False, {}, ("EXECUTION_COST_VALIDATION_REQUIRED",), str(p))

    rows = raw.get("symbols")
    if not isinstance(rows, dict):
        return BrokerCostPolicyStatus(False, mode, execution_validated, {}, ("BROKER_COST_POLICY_SYMBOLS_MISSING",), str(p))

    limits: dict[str, dict[str, Any]] = {}
    reasons: list[str] = []
    for symbol in required_symbols:
        row = rows.get(symbol)
        if not isinstance(row, dict):
            reasons.append(f"BROKER_COST_POLICY_MISSING_{symbol}")
            continue
        try:
            max_spread = float(row["max_spread_points"])
        except Exception:
            reasons.append(f"BROKER_COST_POLICY_INVALID_{symbol}")
            continue
        if max_spread <= 0:
            reasons.append(f"BROKER_COST_POLICY_RANGE_INVALID_{symbol}")
            continue

        limit: dict[str, Any] = {
            "max_spread_points": max_spread,
            "reject_nonpositive_spread": bool(row.get("reject_nonpositive_spread", True)),
            "evidence_percentile": float(row.get("evidence_percentile", 0.95)),
            "slippage_validated": False,
            "expected_slippage_points": 0.0,
            "max_slippage_points": 0.0,
            "cost_basis": "SPREAD_ONLY",
            "adaptive_spread_enabled": bool(row.get("adaptive_spread_enabled", False)),
            "adaptive_elevated_multiple": float(row.get("adaptive_elevated_multiple", 1.5)),
            "adaptive_block_multiple": float(row.get("adaptive_block_multiple", 2.0)),
            "adaptive_p95_block_multiple": float(row.get("adaptive_p95_block_multiple", 1.5)),
            "max_spread_to_stop_ratio": float(row.get("max_spread_to_stop_ratio", 0.25)),
        }

        if mode == EXECUTION_VALIDATED:
            try:
                expected_slippage = float(row["expected_slippage_points"])
                max_slippage = float(row["max_slippage_points"])
            except Exception:
                reasons.append(f"BROKER_COST_POLICY_SLIPPAGE_INVALID_{symbol}")
                continue
            if expected_slippage < 0 or max_slippage < 0 or expected_slippage > max_slippage:
                reasons.append(f"BROKER_COST_POLICY_RANGE_INVALID_{symbol}")
                continue
            limit.update({
                "expected_slippage_points": expected_slippage,
                "max_slippage_points": max_slippage,
                "slippage_validated": True,
                "cost_basis": "SPREAD_PLUS_VALIDATED_SLIPPAGE",
            })

        limits[symbol] = limit

    if reasons:
        return BrokerCostPolicyStatus(False, mode, execution_validated, {}, tuple(reasons), str(p))

    reason = "BROKER_COST_POLICY_PAPER_APPROVED" if mode == PAPER_ONLY else "BROKER_COST_POLICY_EXECUTION_VALIDATED"
    return BrokerCostPolicyStatus(True, mode, execution_validated, limits, (reason,), str(p))
