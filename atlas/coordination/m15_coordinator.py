from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any

@dataclass(slots=True)
class M15OpportunityPackage:
    symbol: str
    permitted_direction: str
    primary_trigger: dict[str, Any] | None = None
    confirmations: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    freshness: str = 'UNKNOWN'
    coordination_state: str = 'COLLECTING_REPORTS'
    reason_codes: list[str] = field(default_factory=list)
    reports_seen: int = 0
    confluence_count: int = 0
    confluence_level: str = 'SINGLE_SIGNAL'

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

class M15Coordinator:
    ACTIONABLE = {'EARLY_REVERSAL_CANDIDATE', 'VALID_TRIGGER'}

    def build(
        self,
        symbol: str,
        permitted_direction: str,
        reports: list[dict[str, Any]],
        *,
        eligible_agents: set[str] | None = None,
        blocked_reason: str | None = None,
    ) -> M15OpportunityPackage:
        p = M15OpportunityPackage(symbol=symbol, permitted_direction=permitted_direction, reports_seen=len(reports))
        if blocked_reason:
            p.coordination_state = 'SLEEPING'
            p.reason_codes.append(blocked_reason)
            return p
        actionable: list[dict[str, Any]] = []
        for report in reports:
            agent = report.get('agent_id') or report.get('specialist', 'UNKNOWN')
            if eligible_agents is not None and agent not in eligible_agents:
                continue
            status = report.get('status') or report.get('pattern_state', 'UNKNOWN')
            data = report.get('data', report)
            direction = self._direction(agent, data)
            if status in self.ACTIONABLE and direction not in {'NONE', permitted_direction}:
                p.conflicts.append({'agent': agent, 'status': status, 'direction': direction})
                continue
            if status in self.ACTIONABLE:
                contract_errors = self._contract_errors(status, data)
                if contract_errors:
                    p.conflicts.append({'agent': agent, 'status': status, 'direction': direction, 'contract_errors': contract_errors})
                    continue
                actionable.append({'agent': agent, 'status': status, 'data': data, 'direction': direction})

        if p.conflicts and not actionable:
            p.coordination_state = 'CONFLICT_REVIEW'; p.reason_codes.append('CONFLICTING_EVIDENCE'); return p
        if not actionable:
            p.reason_codes.append('NO_ACTIONABLE_M15_TRIGGER'); return p

        actionable.sort(key=self._priority)
        primary = actionable[0]
        p.primary_trigger = self._trigger_summary(primary)
        p.freshness = self._freshness(primary['data'])

        for other in actionable[1:]:
            if not self._same_direction(primary, other):
                p.conflicts.append({'agent': other['agent'], 'status': other['status'], 'direction': other['direction']})
                continue
            if self._same_event(primary, other):
                p.duplicates.append({'agent': other['agent'], 'relationship': 'SAME_EVENT_MULTIPLE_DESCRIPTIONS'})
            else:
                p.confirmations.append({'agent': other['agent'], 'type': other['data'].get('last_reason_code','CONFIRMATION'), 'relationship': 'INDEPENDENT_CONFIRMATION'})

        p.confluence_count = 1 + len(p.confirmations)
        if p.confluence_count >= 3:
            p.confluence_level = 'STRONG_MULTI_AGENT'
            p.reason_codes.append('M15_STRONG_MULTI_AGENT_CONFLUENCE')
        elif p.confluence_count == 2:
            p.confluence_level = 'CONFIRMED_BY_SECOND_AGENT'
            p.reason_codes.append('M15_TWO_AGENT_CONFLUENCE')

        if primary['agent'] == 'M15_MULTIPLE_TOP_BOTTOM' and primary['status'] == 'EARLY_REVERSAL_CANDIDATE' and not any(c['agent']=='M15_IMPULSE_CORRECTION' for c in p.confirmations):
            p.coordination_state = 'WAITING_FOR_CONFIRMATION'
            p.reason_codes.append('EARLY_PATTERN_SIGNAL_STRUCTURE_CONFIRMATION_PENDING')
        elif p.conflicts:
            p.coordination_state = 'CONFLICT_REVIEW'; p.reason_codes.append('CONFLICTING_EVIDENCE')
        elif p.freshness != 'VALID':
            p.coordination_state = 'EXPIRED'; p.reason_codes.append('TRIGGER_NOT_FRESH')
        else:
            p.coordination_state = 'READY_FOR_SUPERVISOR_REVIEW'; p.reason_codes.append('M15_PACKAGE_READY')
        return p

    @staticmethod
    def _priority(r: dict[str, Any]) -> tuple[int, int]:
        # A fully validated trigger outranks an early candidate. An early
        # Multiple Top/Bottom signal must never block an independently valid
        # trigger from another eligible specialist.
        agent_order = {'M15_IMPULSE_CORRECTION':0,'M15_MULTIPLE_TOP_BOTTOM':1,'M15_CANDLESTICK_SR':2}
        return (0 if r['status']=='VALID_TRIGGER' else 1, agent_order.get(r['agent'], 5))

    @staticmethod
    def _freshness(data: dict[str, Any]) -> str:
        return str(data.get('freshness') or ('STALE' if data.get('pattern_state')=='STALE' else 'VALID'))

    @classmethod
    def _trigger_summary(cls, report: dict[str, Any]) -> dict[str, Any]:
        d=report['data']
        entry = d.get('entry_reference') if d.get('entry_reference') is not None else d.get('trigger_entry_reference')
        trigger_time = d.get('trigger_time') or d.get('bos_time') or d.get('structural_break_time') or d.get('confirmation_time') or d.get('neckline_break_time') or d.get('breakout_time')
        event_id = d.get('event_id') or cls._event_identity(report['agent'], trigger_time, entry)
        return {
            'agent': report['agent'], 'status': report['status'],
            'pattern_type': d.get('pattern_type'), 'direction': report['direction'],
            'entry_reference': entry, 'raw_stop_anchor': d.get('raw_stop_anchor'),
            'applied_buffer': d.get('applied_buffer'), 'final_stop': d.get('final_stop'),
            'trigger_time': trigger_time, 'event_id': event_id,
            'freshness': cls._freshness(d), 'reason_code': d.get('last_reason_code'),
            'zone_timeframe': d.get('zone_timeframe'), 'zone_kind': d.get('zone_kind'),
            'zone_low': d.get('zone_low'), 'zone_high': d.get('zone_high'),
            'counter_move': d.get('counter_move'), 'quality': d.get('quality'),
            'research_note': d.get('research_note'),
        }

    @staticmethod
    def _event_identity(agent: str, trigger_time: Any, entry: Any) -> str | None:
        if trigger_time is None and entry is None:
            return None
        return f"{agent}|{trigger_time or 'NA'}|{entry if entry is not None else 'NA'}"

    @staticmethod
    def _contract_errors(status: str, data: dict[str, Any]) -> list[str]:
        if status not in {'EARLY_REVERSAL_CANDIDATE', 'VALID_TRIGGER'}:
            return []
        errors: list[str] = []
        entry = data.get('entry_reference') if data.get('entry_reference') is not None else data.get('trigger_entry_reference')
        if entry is None:
            errors.append('MISSING_ENTRY_REFERENCE')
        if data.get('final_stop') is None:
            errors.append('MISSING_FINAL_STOP')
        if data.get('raw_stop_anchor') is None:
            errors.append('MISSING_STRUCTURAL_STOP_ANCHOR')
        return errors

    @staticmethod
    def _direction(agent: str, data: dict[str, Any]) -> str:
        if agent=='M15_MULTIPLE_TOP_BOTTOM':
            pt=data.get('pattern_type',''); return 'LONG' if 'BOTTOM' in pt else ('SHORT' if 'TOP' in pt else 'NONE')
        if agent=='M15_IMPULSE_CORRECTION' and data.get('phase')=='VALID_TRIGGER':
            return 'LONG' if data.get('trend')=='BULLISH' else ('SHORT' if data.get('trend')=='BEARISH' else 'NONE')
        return str(data.get('direction') or data.get('permitted_direction') or 'NONE')

    @classmethod
    def _same_direction(cls,a,b): return cls._direction(a['agent'],a['data'])==cls._direction(b['agent'],b['data'])!='NONE'

    @staticmethod
    def _trigger_time(data: dict[str, Any]) -> Any:
        return (data.get('trigger_time') or data.get('bos_time') or
                data.get('structural_break_time') or data.get('confirmation_time') or
                data.get('neckline_break_time') or data.get('breakout_time'))

    @classmethod
    def _same_event(cls, a: dict[str, Any], b: dict[str, Any]) -> bool:
        # Different specialist families are independent evidence even when they
        # trigger on the same candle/price area. This allows a channel +
        # candlestick (or other two-family) confluence to reach the Supervisor as
        # confirmation rather than being collapsed as a duplicate.
        if a.get('agent') != b.get('agent') and 'M15_CANDLESTICK_SR' in {a.get('agent'), b.get('agent')}:
            # The candlestick specialist is intentionally independent evidence
            # even if it completes on the same M15 bar as a channel/flag/etc.
            return False
        da, db = a['data'], b['data']
        ea, eb = da.get('event_id'), db.get('event_id')
        if ea and eb:
            return ea == eb
        ta, tb = cls._trigger_time(da), cls._trigger_time(db)
        if ta and tb:
            return ta == tb
        pa = da.get('entry_reference') or da.get('trigger_entry_reference')
        pb = db.get('entry_reference') or db.get('trigger_entry_reference')
        return pa is not None and pb is not None and abs(float(pa)-float(pb)) <= 1e-9
