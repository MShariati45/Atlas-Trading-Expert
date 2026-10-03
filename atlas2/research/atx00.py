"""ATX-00 replay/accounting fidelity primitives.

Research-only helpers for manually specified golden cases. They do not resolve
owner strategy outcomes or authorize trading.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import json

from atlas2.core.canonical import canonical_json_text
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64


ATX00_ALIAS = "ATX-00"
SCENARIO_SET_VERSION = "atx00-golden-v1"
@dataclass(frozen=True, slots=True)
class BarrierBar:
    open_time_us: int
    close_time_us: int
    open: int
    high: int
    low: int
    close: int
    price_basis: str

    def validate(self) -> None:
        validate_utc_micros(self.open_time_us)
        validate_utc_micros(self.close_time_us)
        if self.close_time_us <= self.open_time_us:
            raise ValueError("bar close must follow open")
        for value in (self.open, self.high, self.low, self.close):
            validate_int64(value)
            if value <= 0:
                raise ValueError("bar prices must be positive")
        if self.price_basis not in {"BID", "ASK"}:
            raise ValueError("price_basis must be BID/ASK")
        if not self.low <= min(self.open, self.close):
            raise ValueError("invalid bar low")
        if not max(self.open, self.close) <= self.high:
            raise ValueError("invalid bar high")
@dataclass(frozen=True, slots=True)
class BarrierResolution:
    status: str
    exit_reason: str | None
    exit_price: int | None
    path_resolution: str
    ambiguity: str | None = None


def resolve_barrier_ohlc(
    *,
    direction: str,
    stop_price: int,
    target_price: int,
    bar: BarrierBar,
) -> BarrierResolution:
    """Resolve only what OHLC can prove; never choose a favorable same-bar order."""
    bar.validate()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG/SHORT")
    required_basis = "BID" if direction == "LONG" else "ASK"
    if bar.price_basis != required_basis:
        raise ValueError(f"{direction} exits require {required_basis} OHLC")
    validate_int64(stop_price)
    validate_int64(target_price)
    if stop_price <= 0 or target_price <= 0:
        raise ValueError("barrier prices must be positive")
    if direction == "LONG":
        if stop_price >= target_price:
            raise ValueError("long stop must be below target")
        if bar.open <= stop_price:
            return BarrierResolution(
                "RESOLVED", "STOP", bar.open, "M15_OHLC", "GAP_THROUGH_STOP"
            )
        if bar.open >= target_price:
            return BarrierResolution(
                "RESOLVED", "TARGET", target_price, "M15_OHLC", "GAP_THROUGH_TARGET"
            )
        stop_hit = bar.low <= stop_price
        target_hit = bar.high >= target_price
    else:
        if stop_price <= target_price:
            raise ValueError("short stop must be above target")
        if bar.open >= stop_price:
            return BarrierResolution(
                "RESOLVED", "STOP", bar.open, "M15_OHLC", "GAP_THROUGH_STOP"
            )
        if bar.open <= target_price:
            return BarrierResolution(
                "RESOLVED", "TARGET", target_price, "M15_OHLC", "GAP_THROUGH_TARGET"
            )
        stop_hit = bar.high >= stop_price
        target_hit = bar.low <= target_price

    if stop_hit and target_hit:
        return BarrierResolution(
            "AMBIGUOUS", None, None, "M15_OHLC", "SAME_BAR_STOP_TARGET_ORDER"
        )
    if stop_hit:
        return BarrierResolution("RESOLVED", "STOP", stop_price, "M15_OHLC")
    if target_hit:
        return BarrierResolution("RESOLVED", "TARGET", target_price, "M15_OHLC")
    return BarrierResolution("OPEN", None, None, "M15_OHLC")


@dataclass(frozen=True, slots=True)
class StopUpdate:
    requested_at_us: int
    requested_stop: int
    status: str
    resolved_at_us: int
    source_seq: int | None = None

    def validate(self) -> None:
        validate_utc_micros(self.requested_at_us)
        validate_utc_micros(self.resolved_at_us)
        validate_int64(self.requested_stop)
        if self.requested_stop <= 0:
            raise ValueError("requested stop must be positive")
        if self.status not in {"ACKED", "REJECTED"}:
            raise ValueError("invalid stop update status")
        if self.resolved_at_us < self.requested_at_us:
            raise ValueError("stop update cannot resolve before request")
        if self.source_seq is not None:
            validate_int64(self.source_seq)
            if self.source_seq < 0:
                raise ValueError("source_seq cannot be negative")


def _ordered_stop_updates(updates: tuple[StopUpdate, ...]) -> list[StopUpdate]:
    for update in updates:
        update.validate()
    groups: dict[int, list[StopUpdate]] = {}
    for update in updates:
        groups.setdefault(update.resolved_at_us, []).append(update)
    for group in groups.values():
        if len(group) > 1:
            seqs = [item.source_seq for item in group]
            if any(seq is None for seq in seqs) or len(set(seqs)) != len(seqs):
                raise ValueError("same-time stop updates require unique source_seq")
    return sorted(
        updates,
        key=lambda item: (
            item.resolved_at_us,
            -1 if item.source_seq is None else item.source_seq,
        ),
    )


def effective_stop_at(
    *, initial_stop: int, updates: tuple[StopUpdate, ...], as_of_us: int
) -> int:
    """A requested stop does not become active until an ACK is observed."""
    validate_int64(initial_stop)
    if initial_stop <= 0:
        raise ValueError("initial stop must be positive")
    validate_utc_micros(as_of_us)
    active = initial_stop
    for update in _ordered_stop_updates(updates):
        if update.resolved_at_us > as_of_us:
            break
        if update.status == "ACKED":
            active = update.requested_stop
    return active


@dataclass(frozen=True, slots=True)
class Fill:
    time_us: int
    volume_units: int
    price: int
    source_seq: int | None = None
    commission_micro: int = 0
    swap_cost_micro: int = 0

    def validate(self) -> None:
        validate_utc_micros(self.time_us)
        validate_int64(self.volume_units)
        validate_int64(self.price)
        if self.price <= 0:
            raise ValueError("fill price must be positive")
        if self.source_seq is not None:
            validate_int64(self.source_seq)
            if self.source_seq < 0:
                raise ValueError("source_seq cannot be negative")
        validate_int64(self.commission_micro)
        validate_int64(self.swap_cost_micro)
        if self.volume_units <= 0:
            raise ValueError("fill volume must be positive")
        if self.commission_micro < 0 or self.swap_cost_micro < 0:
            raise ValueError("fill costs cannot be negative")


def _ordered_trade_events(
    entry_fills: tuple[Fill, ...],
    exit_fills: tuple[Fill, ...],
) -> list[tuple[str, Fill]]:
    events = [
        *(("ENTRY", fill) for fill in entry_fills),
        *(("EXIT", fill) for fill in exit_fills),
    ]
    for _, fill in events:
        fill.validate()
    groups: dict[int, list[Fill]] = {}
    for _, fill in events:
        groups.setdefault(fill.time_us, []).append(fill)
    for group in groups.values():
        if len(group) > 1:
            seqs = [item.source_seq for item in group]
            if any(seq is None for seq in seqs) or len(set(seqs)) != len(seqs):
                raise ValueError("same-time fills require unique source_seq")
    return sorted(
        events,
        key=lambda item: (
            item[1].time_us,
            -1 if item[1].source_seq is None else item[1].source_seq,
        ),
    )


@dataclass(frozen=True, slots=True)
class CashReconciliation:
    entry_volume_units: int
    exit_volume_units: int
    open_volume_units: int
    gross_cash_micro: int
    explicit_cost_micro: int
    net_cash_micro: int


def reconcile_fifo_cash(
    *,
    direction: str,
    entry_fills: tuple[Fill, ...],
    exit_fills: tuple[Fill, ...],
    cash_per_price_unit_micro: int,
    extra_cost_micro: int = 0,
) -> CashReconciliation:
    """Reconcile realized cash on actual fills using an explicit conversion factor."""
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG/SHORT")
    validate_int64(cash_per_price_unit_micro)
    validate_int64(extra_cost_micro)
    if cash_per_price_unit_micro <= 0:
        raise ValueError("cash conversion factor must be positive")
    if extra_cost_micro < 0:
        raise ValueError("extra cost cannot be negative")
    events = _ordered_trade_events(entry_fills, exit_fills)
    entries: list[list[int]] = []
    entry_volume = 0
    exit_volume = 0

    sign = 1 if direction == "LONG" else -1
    gross = 0
    cursor = 0
    for kind, fill in events:
        if kind == "ENTRY":
            entries.append([fill.volume_units, fill.price])
            entry_volume += fill.volume_units
            continue

        available = entry_volume - exit_volume
        if fill.volume_units > available:
            raise ValueError("exit exceeds position available at that time")
        exit_volume += fill.volume_units
        remaining = fill.volume_units
        while remaining:
            while cursor < len(entries) and entries[cursor][0] == 0:
                cursor += 1
            if cursor >= len(entries):
                raise ValueError("exit volume exceeds available entry volume")
            matched = min(remaining, entries[cursor][0])
            entry_price = entries[cursor][1]
            gross += (
                sign
                * (fill.price - entry_price)
                * matched
                * cash_per_price_unit_micro
            )
            entries[cursor][0] -= matched
            remaining -= matched

    explicit_cost = extra_cost_micro + sum(
        fill.commission_micro + fill.swap_cost_micro
        for fill in (*entry_fills, *exit_fills)
    )
    net = gross - explicit_cost
    for value in (gross, explicit_cost, net):
        validate_int64(value)
    return CashReconciliation(
        entry_volume,
        exit_volume,
        entry_volume - exit_volume,
        gross,
        explicit_cost,
        net,
    )


def atx00_preregistration_payload(
    *,
    target_commit: str,
    baseline_policy_version: str,
    scenario_set_version: str = SCENARIO_SET_VERSION,
) -> dict:
    if not target_commit or not baseline_policy_version:
        raise ValueError("target commit and baseline policy version are required")
    return {
        "alias": ATX00_ALIAS,
        "question": "Does replay obey current chronology and accounting?",
        "experiment_class": "ENGINEERING_FIDELITY",
        "registry_experiment_type": "ENGINEERING",
        "target_commit": target_commit,
        "baseline_policy_version": baseline_policy_version,
        "scenario_set_version": scenario_set_version,
        "model_search": False,
        "gate": {
            "required": "reproducible outcomes and zero unexplained causality/policy/accounting violations",
            "dependent_tests_invalid_if": [
                "unresolved_path_error",
                "unresolved_clock_error",
                "unexplained_accounting_error",
            ],
        },
        "source_requirements": [
            "versioned_quotes_or_fills",
            "account_state",
            "clock_mapping",
            "management_acknowledgements",
        ],
        "authority": "LAB_ONLY_NO_ORDER",
    }


def register_atx00(
    registry,
    *,
    target_commit: str,
    baseline_policy_version: str,
    registered_by: str,
    request_key: str,
):
    """Register ATX-00 through the existing registry as ENGINEERING only."""
    return registry.register_experiment(
        atx00_preregistration_payload(
            target_commit=target_commit,
            baseline_policy_version=baseline_policy_version,
        ),
        registered_by,
        request_key,
        experiment_type="ENGINEERING",
    )


def run_golden_cases() -> dict:
    """Return a deterministic self-check packet for the first ATX-00 slice."""
    t0 = 1_700_000_000_000_000
    ambiguous = resolve_barrier_ohlc(
        direction="LONG",
        stop_price=95,
        target_price=105,
        bar=BarrierBar(t0, t0 + 900_000_000, 100, 106, 94, 101, "BID"),
    )
    gap = resolve_barrier_ohlc(
        direction="LONG",
        stop_price=95,
        target_price=105,
        bar=BarrierBar(t0, t0 + 900_000_000, 92, 99, 90, 96, "BID"),
    )
    update = StopUpdate(t0 + 1, 100, "ACKED", t0 + 3)
    rejected = StopUpdate(t0 + 4, 101, "REJECTED", t0 + 5)
    stop_before_ack = effective_stop_at(
        initial_stop=95, updates=(update, rejected), as_of_us=t0 + 2
    )
    stop_after_ack = effective_stop_at(
        initial_stop=95, updates=(update, rejected), as_of_us=t0 + 6
    )
    cash = reconcile_fifo_cash(
        direction="LONG",
        entry_fills=(
            Fill(t0 + 10, 2, 100, commission_micro=3),
            Fill(t0 + 11, 1, 101, commission_micro=2),
        ),
        exit_fills=(Fill(t0 + 20, 2, 104, commission_micro=4),),
        cash_per_price_unit_micro=10,
        extra_cost_micro=1,
    )
    converted = reconcile_fifo_cash(
        direction="LONG",
        entry_fills=(Fill(t0 + 30, 1, 100),),
        exit_fills=(Fill(t0 + 40, 1, 102),),
        cash_per_price_unit_micro=12,
    )
    window = RiskWindow(t0, t0 + 100)
    risk = concurrent_risk_at(
        commitments=(
            RiskCommitment("open", t0, None, 40),
            RiskCommitment("pending", t0 + 1, None, 70),
        ),
        as_of_us=t0 + 2,
        cap_cash_micro=100,
    )
    account = reconcile_account_balance(
        starting_balance_micro=1_000,
        realized_trade_cash_micro=(100, -30),
        exogenous_cash_micro=(10,),
        observed_ending_balance_micro=1_080,
    )
    causal_feature = feature_available_at_decision(
        event_time_us=t0 - 10,
        available_at_us=t0 - 5,
        confirmation_time_us=t0 - 1,
        decision_time_us=t0,
    )
    leaked_feature = feature_available_at_decision(
        event_time_us=t0 - 10,
        available_at_us=t0 - 5,
        confirmation_time_us=t0 + 1,
        decision_time_us=t0,
    )

    cases = {
        "same_bar_stop_target": ambiguous.status == "AMBIGUOUS",
        "gap_through_stop_uses_first_price": (
            gap.status == "RESOLVED"
            and gap.exit_reason == "STOP"
            and gap.exit_price == 92
        ),
        "stop_request_needs_ack": stop_before_ack == 95,
        "rejected_stop_does_not_apply": stop_after_ack == 100,
        "partial_fill_cash_reconciles": (
            cash.entry_volume_units == 3
            and cash.exit_volume_units == 2
            and cash.open_volume_units == 1
            and cash.gross_cash_micro == 80
            and cash.explicit_cost_micro == 10
            and cash.net_cash_micro == 70
        ),
        "explicit_pair_conversion_factor": converted.net_cash_micro == 24,
        "daily_boundary_is_half_open": (
            window.contains(t0 + 99) and not window.contains(t0 + 100)
        ),
        "pending_and_open_risk_are_concurrent": (
            risk.total_risk_cash_micro == 110
            and not risk.within_cap
            and risk.active_commitment_ids == ("open", "pending")
        ),
        "account_cash_reconciles": account.reconciled,
        "feature_confirmation_must_be_causal": (
            causal_feature and not leaked_feature
        ),
    }
    return {
        "alias": ATX00_ALIAS,
        "scenario_set_version": SCENARIO_SET_VERSION,
        "slice": "ATX00-1",
        "authority": "LAB_ONLY_NO_ORDER",
        "cases": cases,
        "pass": all(cases.values()),
        "remaining_atx00_coverage": [
            "real_quote_fill_adapter",
            "historical_clock_mapping_adapter",
            "management_acknowledgement_adapter",
            "full_chronological_account_replay_integration",
        ],
    }


@dataclass(frozen=True, slots=True)
class RiskWindow:
    start_us: int
    end_us: int

    def validate(self) -> None:
        validate_utc_micros(self.start_us)
        validate_utc_micros(self.end_us)
        if self.end_us <= self.start_us:
            raise ValueError("risk window must be nonempty")

    def contains(self, time_us: int) -> bool:
        self.validate()
        validate_utc_micros(time_us)
        return self.start_us <= time_us < self.end_us


@dataclass(frozen=True, slots=True)
class RiskCommitment:
    commitment_id: str
    start_us: int
    end_us: int | None
    risk_cash_micro: int

    def validate(self) -> None:
        if not self.commitment_id:
            raise ValueError("commitment_id is required")
        validate_utc_micros(self.start_us)
        if self.end_us is not None:
            validate_utc_micros(self.end_us)
            if self.end_us <= self.start_us:
                raise ValueError("commitment end must follow start")
        validate_int64(self.risk_cash_micro)
        if self.risk_cash_micro < 0:
            raise ValueError("risk commitment cannot be negative")


@dataclass(frozen=True, slots=True)
class ConcurrentRiskSnapshot:
    as_of_us: int
    total_risk_cash_micro: int
    cap_cash_micro: int
    within_cap: bool
    active_commitment_ids: tuple[str, ...]


def concurrent_risk_at(
    *,
    commitments: tuple[RiskCommitment, ...],
    as_of_us: int,
    cap_cash_micro: int,
) -> ConcurrentRiskSnapshot:
    validate_utc_micros(as_of_us)
    validate_int64(cap_cash_micro)
    if cap_cash_micro < 0:
        raise ValueError("risk cap cannot be negative")
    ids = [item.commitment_id for item in commitments]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate risk commitment_id")
    active = []
    total = 0
    for item in commitments:
        item.validate()
        if item.start_us <= as_of_us and (
            item.end_us is None or as_of_us < item.end_us
        ):
            active.append(item.commitment_id)
            total += item.risk_cash_micro
    validate_int64(total)
    return ConcurrentRiskSnapshot(
        as_of_us,
        total,
        cap_cash_micro,
        total <= cap_cash_micro,
        tuple(sorted(active)),
    )


@dataclass(frozen=True, slots=True)
class AccountCashReconciliation:
    expected_ending_balance_micro: int
    observed_ending_balance_micro: int
    difference_micro: int
    reconciled: bool


def reconcile_account_balance(
    *,
    starting_balance_micro: int,
    realized_trade_cash_micro: tuple[int, ...],
    exogenous_cash_micro: tuple[int, ...],
    observed_ending_balance_micro: int,
) -> AccountCashReconciliation:
    for value in (
        starting_balance_micro,
        observed_ending_balance_micro,
        *realized_trade_cash_micro,
        *exogenous_cash_micro,
    ):
        validate_int64(value)
    expected = (
        starting_balance_micro
        + sum(realized_trade_cash_micro)
        + sum(exogenous_cash_micro)
    )
    diff = observed_ending_balance_micro - expected
    validate_int64(expected)
    validate_int64(diff)
    return AccountCashReconciliation(
        expected,
        observed_ending_balance_micro,
        diff,
        diff == 0,
    )


def feature_available_at_decision(
    *,
    event_time_us: int,
    available_at_us: int,
    decision_time_us: int,
    confirmation_time_us: int | None = None,
) -> bool:
    """Return whether a feature was causally usable at the historical decision.

    If confirmation_time_us is absent, available_at_us is treated as the
    authoritative usability timestamp for this research primitive.
    """
    validate_utc_micros(event_time_us)
    validate_utc_micros(available_at_us)
    validate_utc_micros(decision_time_us)
    if confirmation_time_us is not None:
        validate_utc_micros(confirmation_time_us)
    if available_at_us < event_time_us:
        raise ValueError("feature availability cannot precede event time")
    if confirmation_time_us is not None and confirmation_time_us < event_time_us:
        raise ValueError("feature confirmation cannot precede event time")
    if event_time_us > decision_time_us:
        return False
    if available_at_us > decision_time_us:
        return False
    if confirmation_time_us is not None and confirmation_time_us > decision_time_us:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    if not args.self_check:
        parser.error("--self-check is required")
    packet = run_golden_cases()
    print(canonical_json_text(packet))
    return 0 if packet["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
