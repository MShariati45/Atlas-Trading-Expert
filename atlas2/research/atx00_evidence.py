"""ATX-00 immutable evidence adapters and chronological account replay.

Research/Lab only. This module reads Atlas v2 immutable evidence or consumes an
explicit normalized execution bundle. It has no broker/network/order authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from atlas2.core.canonical import canonical_json_text, domain_digest
from atlas2.core.enums import RunMode, ViewClass
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64
from atlas2.data.views import MarketView
from atlas2.store.repository import Store


EXECUTION_EVENT_KINDS = frozenset({
    "ENTRY_FILL",
    "EXIT_FILL",
    "RISK_START",
    "RISK_END",
    "CASH_ADJUSTMENT",
    "STOP_REQUEST",
    "STOP_ACK",
    "STOP_REJECT",
})


@dataclass(frozen=True, slots=True)
class ReplayQuote:
    fact_id: str
    time_us: int
    source_seq: int
    bid: int
    ask: int
    available_at_us: int
    taint: int


@dataclass(frozen=True, slots=True)
class QuoteEvidenceSlice:
    dataset_id: str
    instrument_id: str
    clock_profile_id: str
    tzdata_version: str
    start_us: int
    end_us: int
    as_of_us: int
    quote_digest: str
    quotes: tuple[ReplayQuote, ...]
def _sealed_dataset_row(store: Store, dataset_id: str):
    row = store.conn.execute(
        "SELECT * FROM data_datasets WHERE dataset_id=?", (dataset_id,)
    ).fetchone()
    if row is None:
        raise ValueError("unknown dataset")
    seal = store.conn.execute(
        """SELECT child_set_digest FROM sys_seals
           WHERE aggregate_kind='data_datasets' AND aggregate_id=?""",
        (dataset_id,),
    ).fetchone()
    if seal is None:
        raise ValueError("dataset must be sealed")
    if seal[0] != store.child_digest("data_datasets", dataset_id):
        raise ValueError("dataset seal mismatch")
    return row


def _verify_dataset_clock_binding(store: Store, dataset_id: str, clock_profile_id: str) -> None:
    rows = store.conn.execute(
        """SELECT DISTINCT o.clock_profile_id
           FROM data_dataset_membership m
           JOIN source_observations o ON o.obs_id=m.obs_id
           WHERE m.dataset_id=?
           ORDER BY o.clock_profile_id""",
        (dataset_id,),
    ).fetchall()
    profiles = tuple(row[0] for row in rows)
    if any(profile != clock_profile_id for profile in profiles):
        raise ValueError("dataset member observation clock profile mismatch")


def bind_quote_evidence(
    store: Store,
    *,
    dataset_id: str,
    instrument_id: str,
    start_us: int,
    end_us: int,
    as_of_us: int,
) -> QuoteEvidenceSlice:
    """Bind causal Atlas QuoteFacts to a deterministic ATX-00 evidence slice."""
    validate_utc_micros(start_us)
    validate_utc_micros(end_us)
    validate_utc_micros(as_of_us)
    if end_us <= start_us:
        raise ValueError("quote evidence window must be nonempty")
    if as_of_us < end_us:
        raise ValueError("as_of_us must cover the requested quote window")

    dataset = _sealed_dataset_row(store, dataset_id)
    specs = json.loads(dataset["instrument_specs_json"])
    if instrument_id not in specs:
        raise ValueError("instrument is not declared in dataset specs")
    _verify_dataset_clock_binding(store, dataset_id, dataset["clock_profile_id"])

    visible = MarketView(
        store,
        dataset_id,
        mode=RunMode.REPLAY,
        actor="atx00",
        purpose="engineering-fidelity",
        request_key_prefix="atx00-quotes",
    ).quotes(
        instrument_id,
        start_us,
        end_us,
        as_of_us,
        view_class=ViewClass.PIT,
    )
    if not visible:
        raise ValueError("no causal quotes in requested window")
    result = []
    keys = set()
    semantic = []
    for item in visible:
        fact = item.fact
        if fact.source_seq is None:
            raise ValueError("ATX-00 quote replay requires source_seq")
        if item.available_at_us > as_of_us:
            raise ValueError("quote availability exceeds replay knowledge time")
        key = (fact.time_us, fact.source_seq)
        if key in keys:
            raise ValueError("duplicate quote source sequence at timestamp")
        keys.add(key)
        quote = ReplayQuote(
            fact.fact_id,
            fact.time_us,
            fact.source_seq,
            fact.bid,
            fact.ask,
            item.available_at_us,
            int(item.taint),
        )
        result.append(quote)
        semantic.append({
            "fact_id": quote.fact_id,
            "time_us": quote.time_us,
            "source_seq": quote.source_seq,
            "bid": quote.bid,
            "ask": quote.ask,
            "available_at_us": quote.available_at_us,
            "taint": quote.taint,
        })
    result.sort(key=lambda q: (q.time_us, q.source_seq, q.fact_id))
    semantic.sort(key=lambda q: (q["time_us"], q["source_seq"], q["fact_id"]))
    digest = domain_digest(
        "atx00-quote-evidence-v1",
        {
            "dataset_id": dataset_id,
            "instrument_id": instrument_id,
            "clock_profile_id": dataset["clock_profile_id"],
            "tzdata_version": dataset["tzdata_version"],
            "start_us": start_us,
            "end_us": end_us,
            "as_of_us": as_of_us,
            "quotes": semantic,
        },
    )
    return QuoteEvidenceSlice(
        dataset_id,
        instrument_id,
        dataset["clock_profile_id"],
        dataset["tzdata_version"],
        start_us,
        end_us,
        as_of_us,
        digest,
        tuple(result),
    )
@dataclass(frozen=True, slots=True)
class ExecutionEvidenceEvent:
    event_id: str
    source_sha256: str
    locator: str
    event_kind: str
    time_us: int
    source_seq: int
    trade_id: str | None = None
    commitment_id: str | None = None
    request_id: str | None = None
    direction: str | None = None
    volume_units: int | None = None
    price: int | None = None
    cash_per_price_unit_micro: int | None = None
    commission_cost_micro: int = 0
    swap_cost_micro: int = 0
    risk_cash_micro: int | None = None
    cash_delta_micro: int | None = None
    stop_price: int | None = None

    def validate(self) -> None:
        if (
            type(self.source_sha256) is not str
            or len(self.source_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_sha256)
        ):
            raise ValueError("source_sha256 must be lowercase sha256 hex")
        if type(self.event_id) is not str or not self.event_id:
            raise ValueError("event_id is required")
        if type(self.locator) is not str or not self.locator:
            raise ValueError("locator is required")
        for name, value in (
            ("trade_id", self.trade_id),
            ("commitment_id", self.commitment_id),
            ("request_id", self.request_id),
        ):
            if value is not None and (type(value) is not str or not value):
                raise ValueError(f"{name} must be nonempty text")
        if self.event_kind not in EXECUTION_EVENT_KINDS:
            raise ValueError("invalid execution event kind")
        validate_utc_micros(self.time_us)
        validate_int64(self.source_seq)
        if self.source_seq < 0:
            raise ValueError("source_seq cannot be negative")
        if self.direction is not None and self.direction not in {"LONG", "SHORT"}:
            raise ValueError("invalid direction")
        for value in (
            self.volume_units,
            self.price,
            self.cash_per_price_unit_micro,
            self.commission_cost_micro,
            self.swap_cost_micro,
            self.risk_cash_micro,
            self.cash_delta_micro,
            self.stop_price,
        ):
            if value is not None:
                validate_int64(value)
        if self.commission_cost_micro < 0 or self.swap_cost_micro < 0:
            raise ValueError("execution costs must be nonnegative")
        if self.event_kind in {"ENTRY_FILL", "EXIT_FILL"}:
            if any(value is not None for value in (
                self.commitment_id, self.request_id, self.risk_cash_micro,
                self.cash_delta_micro, self.stop_price,
            )):
                raise ValueError("fill event carries unrelated fields")
            required = (
                self.trade_id,
                self.direction,
                self.volume_units,
                self.price,
            )
            if any(value is None for value in required):
                raise ValueError("fill event missing required fields")
            if self.volume_units <= 0 or self.price <= 0:
                raise ValueError("fill volume/price must be positive")
            if self.event_kind == "ENTRY_FILL":
                if self.cash_per_price_unit_micro is not None:
                    raise ValueError("ENTRY_FILL must not carry exit conversion")
            elif (
                self.cash_per_price_unit_micro is None
                or self.cash_per_price_unit_micro <= 0
            ):
                raise ValueError("EXIT_FILL requires positive cash conversion")
        elif self.event_kind == "RISK_START":
            if any(value is not None for value in (
                self.trade_id, self.request_id, self.direction, self.volume_units,
                self.price, self.cash_per_price_unit_micro,
                self.cash_delta_micro, self.stop_price,
            )) or self.commission_cost_micro or self.swap_cost_micro:
                raise ValueError("RISK_START carries unrelated fields")
            if self.commitment_id is None or self.risk_cash_micro is None:
                raise ValueError("RISK_START requires commitment and risk")
            if self.risk_cash_micro < 0:
                raise ValueError("risk cannot be negative")
        elif self.event_kind == "RISK_END":
            if any(value is not None for value in (
                self.trade_id, self.request_id, self.direction, self.volume_units,
                self.price, self.cash_per_price_unit_micro,
                self.risk_cash_micro, self.cash_delta_micro, self.stop_price,
            )) or self.commission_cost_micro or self.swap_cost_micro:
                raise ValueError("RISK_END carries unrelated fields")
            if self.commitment_id is None:
                raise ValueError("RISK_END requires commitment")
        elif self.event_kind == "CASH_ADJUSTMENT":
            if any(value is not None for value in (
                self.trade_id, self.commitment_id, self.request_id, self.direction,
                self.volume_units, self.price, self.cash_per_price_unit_micro,
                self.risk_cash_micro, self.stop_price,
            )) or self.commission_cost_micro or self.swap_cost_micro:
                raise ValueError("CASH_ADJUSTMENT carries unrelated fields")
            if self.cash_delta_micro is None:
                raise ValueError("CASH_ADJUSTMENT requires cash delta")
        elif self.event_kind in {"STOP_REQUEST", "STOP_ACK", "STOP_REJECT"}:
            if any(value is not None for value in (
                self.commitment_id, self.direction, self.volume_units, self.price,
                self.cash_per_price_unit_micro, self.risk_cash_micro,
                self.cash_delta_micro,
            )) or self.commission_cost_micro or self.swap_cost_micro:
                raise ValueError("stop event carries unrelated fields")
            if self.trade_id is None or self.request_id is None:
                raise ValueError("stop event requires trade_id and request_id")
            if self.event_kind == "STOP_REQUEST":
                if self.stop_price is None or self.stop_price <= 0:
                    raise ValueError("STOP_REQUEST requires positive stop_price")
            elif self.stop_price is not None:
                raise ValueError("stop resolution must not restate stop_price")


@dataclass(frozen=True, slots=True)
class ExecutionEvidenceBundle:
    source_sha256: str
    bundle_digest: str
    events: tuple[ExecutionEvidenceEvent, ...]


def bind_execution_events(
    events: tuple[ExecutionEvidenceEvent, ...],
) -> ExecutionEvidenceBundle:
    """Validate and content-bind already-normalized broker/account evidence."""
    if not events:
        raise ValueError("execution evidence cannot be empty")
    for event in events:
        event.validate()
    source_hashes = {event.source_sha256 for event in events}
    if len(source_hashes) != 1:
        raise ValueError("one evidence bundle must bind one source blob")
    ids = set()
    locators = set()
    sequences = set()
    ordered = []
    for event in events:
        if event.event_id in ids:
            raise ValueError("duplicate execution event_id")
        if event.locator in locators:
            raise ValueError("duplicate execution source locator")
        if event.source_seq in sequences:
            raise ValueError("duplicate execution source_seq")
        ids.add(event.event_id)
        locators.add(event.locator)
        sequences.add(event.source_seq)
        ordered.append(event)
    ordered.sort(key=lambda e: (e.time_us, e.source_seq, e.event_id))
    source_order = [event.source_seq for event in ordered]
    if source_order != sorted(source_order):
        raise ValueError("execution timestamp conflicts with source sequence")
    semantic = [
        {
            field: getattr(event, field)
            for field in event.__dataclass_fields__
        }
        for event in ordered
    ]
    digest = domain_digest("atx00-execution-evidence-v1", semantic)
    return ExecutionEvidenceBundle(
        next(iter(source_hashes)), digest, tuple(ordered)
    )
@dataclass(frozen=True, slots=True)
class AccountReplayResult:
    starting_balance_micro: int
    ending_balance_micro: int
    realized_gross_micro: int
    incurred_cost_micro: int
    exogenous_cash_micro: int
    open_volume_by_trade_json: str
    active_risk_cash_micro: int
    peak_risk_cash_micro: int
    risk_cap_cash_micro: int
    risk_cap_violations: int
    unresolved_stop_request_ids_json: str
    active_stops_json: str
    replay_digest: str


def replay_account_evidence(
    bundle: ExecutionEvidenceBundle,
    *,
    starting_balance_micro: int,
    risk_cap_cash_micro: int,
) -> AccountReplayResult:
    """Replay normalized evidence chronologically with explicit accounting/capacity."""
    rebound = bind_execution_events(bundle.events)
    if rebound != bundle:
        raise ValueError("execution bundle is not canonically bound")

    validate_int64(starting_balance_micro)
    validate_int64(risk_cap_cash_micro)
    if risk_cap_cash_micro < 0:
        raise ValueError("risk cap cannot be negative")

    positions: dict[str, dict] = {}
    closed_trade_ids: set[str] = set()
    active_risk: dict[str, int] = {}
    seen_commitment_ids: set[str] = set()
    stop_requests: dict[str, tuple[str, int]] = {}
    seen_request_ids: set[str] = set()
    active_stops: dict[str, int] = {}
    balance = starting_balance_micro
    gross_total = 0
    costs_total = 0
    exogenous_total = 0
    peak_risk = 0
    violations = 0
    was_over_cap = False

    for event in bundle.events:
        if event.event_kind == "ENTRY_FILL":
            if event.trade_id in closed_trade_ids:
                raise ValueError("trade_id reused after close")
            state = positions.setdefault(
                event.trade_id,
                {"direction": event.direction, "lots": [], "open_volume": 0},
            )
            if state["direction"] != event.direction:
                raise ValueError("trade direction changed")
            state["lots"].append([event.volume_units, event.price])
            state["open_volume"] += event.volume_units
            validate_int64(state["open_volume"])
            cost = event.commission_cost_micro + event.swap_cost_micro
            balance -= cost
            costs_total += cost
        elif event.event_kind == "EXIT_FILL":
            state = positions.get(event.trade_id)
            if state is None or state["direction"] != event.direction:
                raise ValueError("exit has no matching open trade")
            if event.volume_units > state["open_volume"]:
                raise ValueError("exit exceeds open trade volume")
            remaining = event.volume_units
            sign = 1 if event.direction == "LONG" else -1
            while remaining:
                lot = next((lot for lot in state["lots"] if lot[0]), None)
                if lot is None:
                    raise ValueError("missing entry lot during exit")
                matched = min(remaining, lot[0])
                gross = (
                    sign
                    * (event.price - lot[1])
                    * matched
                    * event.cash_per_price_unit_micro
                )
                gross_total += gross
                balance += gross
                lot[0] -= matched
                remaining -= matched
            state["open_volume"] -= event.volume_units
            if state["open_volume"] == 0:
                closed_trade_ids.add(event.trade_id)
                active_stops.pop(event.trade_id, None)
            cost = event.commission_cost_micro + event.swap_cost_micro
            balance -= cost
            costs_total += cost
        elif event.event_kind == "RISK_START":
            if event.commitment_id in seen_commitment_ids:
                raise ValueError("risk commitment_id reused")
            seen_commitment_ids.add(event.commitment_id)
            active_risk[event.commitment_id] = event.risk_cash_micro
        elif event.event_kind == "RISK_END":
            if event.commitment_id not in active_risk:
                raise ValueError("risk end without active commitment")
            del active_risk[event.commitment_id]
        elif event.event_kind == "CASH_ADJUSTMENT":
            balance += event.cash_delta_micro
            exogenous_total += event.cash_delta_micro
        elif event.event_kind == "STOP_REQUEST":
            state = positions.get(event.trade_id)
            if state is None or state["open_volume"] <= 0:
                raise ValueError("stop request requires open trade")
            if event.request_id in seen_request_ids:
                raise ValueError("stop request_id reused")
            seen_request_ids.add(event.request_id)
            stop_requests[event.request_id] = (event.trade_id, event.stop_price)
        elif event.event_kind in {"STOP_ACK", "STOP_REJECT"}:
            request = stop_requests.get(event.request_id)
            if request is None or request[0] != event.trade_id:
                raise ValueError("stop resolution without matching request")
            if event.event_kind == "STOP_ACK":
                state = positions.get(event.trade_id)
                if state is None or state["open_volume"] <= 0:
                    raise ValueError("stop acknowledgement requires open trade")
                active_stops[event.trade_id] = request[1]
            del stop_requests[event.request_id]

        for value in (balance, gross_total, costs_total, exogenous_total):
            validate_int64(value)
        current_risk = sum(active_risk.values())
        validate_int64(current_risk)
        if current_risk > peak_risk:
            peak_risk = current_risk
        over_cap = current_risk > risk_cap_cash_micro
        if over_cap and not was_over_cap:
            violations += 1
        was_over_cap = over_cap

    open_volume = {
        trade_id: state["open_volume"]
        for trade_id, state in sorted(positions.items())
        if state["open_volume"]
    }
    for value in (
        balance,
        gross_total,
        costs_total,
        exogenous_total,
        sum(active_risk.values()),
        peak_risk,
    ):
        validate_int64(value)
    summary = {
        "source_sha256": bundle.source_sha256,
        "bundle_digest": bundle.bundle_digest,
        "lot_matching_policy": "FIFO_WITHIN_TRADE_ID",
        "exit_direction_semantics": "ORIGINAL_POSITION_DIRECTION",
        "source_seq_semantics": "GLOBAL_STRICT_SOURCE_ORDER",
        "starting_balance_micro": starting_balance_micro,
        "ending_balance_micro": balance,
        "realized_gross_micro": gross_total,
        "incurred_cost_micro": costs_total,
        "exogenous_cash_micro": exogenous_total,
        "open_volume_by_trade": open_volume,
        "active_risk_cash_micro": sum(active_risk.values()),
        "peak_risk_cash_micro": peak_risk,
        "risk_cap_cash_micro": risk_cap_cash_micro,
        "risk_cap_violations": violations,
        "unresolved_stop_requests": sorted(stop_requests),
        "active_stops": dict(sorted(active_stops.items())),
    }
    return AccountReplayResult(
        starting_balance_micro,
        balance,
        gross_total,
        costs_total,
        exogenous_total,
        canonical_json_text(open_volume),
        sum(active_risk.values()),
        peak_risk,
        risk_cap_cash_micro,
        violations,
        canonical_json_text(sorted(stop_requests)),
        canonical_json_text(dict(sorted(active_stops.items()))),
        domain_digest("atx00-account-replay-v1", summary),
    )
