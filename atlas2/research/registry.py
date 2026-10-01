"""Lean P0-3 experiment registry and holdout guard over the shared Atlas Store."""
from __future__ import annotations

from dataclasses import asdict
import sqlite3

from atlas2.model.research import (
    Amendment, Decision, Experiment, Exposure, HoldoutGrant, HoldoutPermission,
    HoldoutSegment, HoldoutStatus, Preregistration, SealState, Trial, TrialEvent,
    TrialResult, ROUTES, GRANT_TYPES, TRIAL_EVENTS,
)
from atlas2.store.repository import Store, StoreConflict, ConflictKind


class ResearchRegistry:
    def __init__(self, store: Store):
        self.store = store
        self.conn = store.conn

    @staticmethod
    def _row_model(cls, row):
        return cls(**dict(row)) if row is not None else None

    def _insert_prereg(self, model: Preregistration) -> None:
        model.validate()
        row = self.conn.execute(
            'SELECT * FROM research_preregistrations WHERE prereg_digest=?',
            (model.prereg_digest,),
        ).fetchone()
        if row:
            if dict(row) != asdict(model):
                raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
            return
        self.conn.execute(
            'INSERT INTO research_preregistrations(prereg_digest,payload_json) VALUES (?,?)',
            (model.prereg_digest, model.payload_json),
        )

    def register_experiment(self, payload: dict, registered_by: str, request_key: str,
                            experiment_type: str = 'CONFIRMATORY') -> Experiment:
        prereg = Preregistration.from_payload(payload)
        predicted = Experiment.create(
            prereg.prereg_digest, registered_by, request_key, experiment_type, 0,
        ).experiment_id
        request_payload = {
            'prereg_digest': prereg.prereg_digest,
            'experiment_type': experiment_type,
        }

        def write(server_time_us: int) -> str:
            self._insert_prereg(prereg)
            exp = Experiment.create(
                prereg.prereg_digest, registered_by, request_key,
                experiment_type, server_time_us,
            )
            self.conn.execute(
                'INSERT INTO research_experiments '
                '(experiment_id,prereg_digest,registered_by,request_key,experiment_type,registered_at_us) '
                'VALUES (?,?,?,?,?,?)',
                tuple(asdict(exp).values()),
            )
            return exp.experiment_id

        receipt = self.store.request_write(
            registered_by, 'research.register_experiment', request_key,
            request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_experiments WHERE experiment_id=?',
            (receipt.result_ref,),
        ).fetchone()
        if row is None or receipt.result_ref != predicted:
            raise RuntimeError('experiment request receipt is inconsistent')
        return self._row_model(Experiment, row)

    def effective_preregistration(self, experiment_id: str) -> tuple[str, int]:
        row = self.conn.execute(
            'SELECT prereg_digest FROM research_experiments WHERE experiment_id=?',
            (experiment_id,),
        ).fetchone()
        if row is None:
            raise ValueError('unknown experiment')
        amendment = self.conn.execute(
            'SELECT sequence,new_payload_digest FROM research_amendments '
            'WHERE experiment_id=? ORDER BY sequence DESC LIMIT 1',
            (experiment_id,),
        ).fetchone()
        return (amendment['new_payload_digest'], amendment['sequence']) if amendment else (row[0], 0)

    def amend_experiment(self, experiment_id: str, new_payload: dict,
                         actor: str, request_key: str) -> Amendment:
        prereg = Preregistration.from_payload(new_payload)
        request_payload = {
            'experiment_id': experiment_id,
            'new_payload_digest': prereg.prereg_digest,
        }

        def write(server_time_us: int) -> str:
            parent_digest, current_sequence = self.effective_preregistration(experiment_id)
            self._insert_prereg(prereg)
            model = Amendment.create(
                experiment_id, current_sequence + 1, parent_digest,
                prereg.prereg_digest, server_time_us,
            )
            try:
                self.conn.execute(
                    'INSERT INTO research_amendments '
                    '(amendment_id,experiment_id,sequence,parent_effective_digest,new_payload_digest,recorded_at_us) '
                    'VALUES (?,?,?,?,?,?)', tuple(asdict(model).values()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError('invalid amendment lineage') from exc
            return model.amendment_id

        receipt = self.store.request_write(
            actor, 'research.amend_experiment', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_amendments WHERE amendment_id=?',
            (receipt.result_ref,),
        ).fetchone()
        if row is None:
            raise RuntimeError('amendment request receipt is inconsistent')
        return self._row_model(Amendment, row)

    def plan_trial(self, experiment_id: str, parameters: object,
                   actor: str, request_key: str) -> Trial:
        from atlas2.model.research import canonical_payload
        parameters_json = canonical_payload(parameters)
        request_payload = {'experiment_id': experiment_id, 'parameters_json': parameters_json}

        def write(_: int) -> str:
            if not self.conn.execute(
                'SELECT 1 FROM research_experiments WHERE experiment_id=?', (experiment_id,)
            ).fetchone():
                raise ValueError('unknown experiment')
            current = self.conn.execute(
                'SELECT max(trial_index) FROM research_trials WHERE experiment_id=?',
                (experiment_id,),
            ).fetchone()[0]
            model = Trial.create(experiment_id, (current or 0) + 1, parameters)
            self.conn.execute(
                'INSERT INTO research_trials(trial_id,experiment_id,trial_index,parameters_json) '
                'VALUES (?,?,?,?)', tuple(asdict(model).values()),
            )
            return model.trial_id

        receipt = self.store.request_write(
            actor, 'research.plan_trial', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_trials WHERE trial_id=?', (receipt.result_ref,)
        ).fetchone()
        return self._row_model(Trial, row)

    def _experiment_for_trial(self, trial_id: str) -> str:
        row = self.conn.execute(
            'SELECT experiment_id FROM research_trials WHERE trial_id=?', (trial_id,)
        ).fetchone()
        if row is None:
            raise ValueError('unknown trial')
        return row[0]

    def _next_evidence_order(self, experiment_id: str) -> int:
        event_max = self.conn.execute(
            'SELECT max(e.evidence_order) FROM research_trial_events e '
            'JOIN research_trials t ON t.trial_id=e.trial_id WHERE t.experiment_id=?',
            (experiment_id,),
        ).fetchone()[0]
        exposure_max = self.conn.execute(
            'SELECT max(x.evidence_order) FROM research_exposures x '
            'JOIN research_holdout_grants g ON g.grant_id=x.grant_id WHERE g.experiment_id=?',
            (experiment_id,),
        ).fetchone()[0]
        return max(event_max or 0, exposure_max or 0) + 1

    def _trial_pin(self, trial_id: str) -> tuple[str, int] | None:
        row = self.conn.execute(
            "SELECT effective_prereg_digest,amendment_sequence FROM research_trial_events "
            "WHERE trial_id=? AND event='STARTED' ORDER BY evidence_order LIMIT 1",
            (trial_id,),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def _sequence_for_digest(self, experiment_id: str, digest: str) -> int:
        initial = self.conn.execute(
            'SELECT prereg_digest FROM research_experiments WHERE experiment_id=?',
            (experiment_id,),
        ).fetchone()
        if initial is None:
            raise ValueError('unknown experiment')
        if initial[0] == digest:
            return 0
        row = self.conn.execute(
            'SELECT sequence FROM research_amendments WHERE experiment_id=? AND new_payload_digest=? '
            'ORDER BY sequence DESC LIMIT 1',
            (experiment_id, digest),
        ).fetchone()
        if row is None:
            raise ValueError('digest is not in experiment preregistration lineage')
        return row[0]

    def record_trial_event(self, trial_id: str, event: str,
                           actor: str, request_key: str) -> TrialEvent:
        if event not in TRIAL_EVENTS:
            raise ValueError('invalid trial event')
        request_payload = {'trial_id': trial_id, 'event': event}

        def write(server_time_us: int) -> str:
            experiment_id = self._experiment_for_trial(trial_id)
            pin = self._trial_pin(trial_id)
            if pin is not None and event != 'STARTED':
                effective, sequence = pin
            else:
                effective, sequence = self.effective_preregistration(experiment_id)
            if event == 'STARTED' and pin is not None:
                raise ValueError('trial already started')
            model = TrialEvent.create(
                trial_id, event, effective, sequence,
                self._next_evidence_order(experiment_id), server_time_us,
            )
            self.conn.execute(
                'INSERT INTO research_trial_events '
                '(event_id,trial_id,event,effective_prereg_digest,amendment_sequence,evidence_order,recorded_at_us) '
                'VALUES (?,?,?,?,?,?,?)', tuple(asdict(model).values()),
            )
            return model.event_id

        receipt = self.store.request_write(
            actor, 'research.trial_event', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_trial_events WHERE event_id=?', (receipt.result_ref,)
        ).fetchone()
        return self._row_model(TrialEvent, row)

    def record_trial_result(self, trial_id: str, result_kind: str, attempt_id: str,
                            payload: object, actor: str, request_key: str) -> TrialResult:
        request_payload = {
            'trial_id': trial_id, 'result_kind': result_kind,
            'attempt_id': attempt_id, 'payload': payload,
        }

        def write(server_time_us: int) -> str:
            self._experiment_for_trial(trial_id)
            pin = self._trial_pin(trial_id)
            if pin is None:
                raise ValueError('trial result requires STARTED event')
            effective, _ = pin
            model = TrialResult.create(
                trial_id, result_kind, attempt_id, effective, payload, server_time_us,
            )
            self.conn.execute(
                'INSERT INTO research_trial_results '
                '(result_id,trial_id,result_kind,attempt_id,effective_prereg_digest,payload_json,recorded_at_us) '
                'VALUES (?,?,?,?,?,?,?)', tuple(asdict(model).values()),
            )
            return model.result_id

        receipt = self.store.request_write(
            actor, 'research.trial_result', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_trial_results WHERE result_id=?', (receipt.result_ref,)
        ).fetchone()
        return self._row_model(TrialResult, row)

    def decide(self, experiment_id: str, payload: object,
               actor: str, request_key: str) -> Decision:
        request_payload = {'experiment_id': experiment_id, 'decision': payload}

        def write(server_time_us: int) -> str:
            if not self.conn.execute(
                'SELECT 1 FROM research_experiments WHERE experiment_id=?', (experiment_id,)
            ).fetchone():
                raise ValueError('unknown experiment')
            model = Decision.create(experiment_id, payload, server_time_us)
            self.conn.execute(
                'INSERT INTO research_decisions(decision_id,experiment_id,payload_json,recorded_at_us) '
                'VALUES (?,?,?,?)', tuple(asdict(model).values()),
            )
            return model.decision_id

        receipt = self.store.request_write(
            actor, 'research.decision', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_decisions WHERE decision_id=?', (receipt.result_ref,)
        ).fetchone()
        return self._row_model(Decision, row)

    def add_holdout_segment(self, instrument_id: str, start_us: int, end_us: int) -> HoldoutSegment:
        model = HoldoutSegment.create(instrument_id, start_us, end_us)
        with self.store.transaction():
            row = self.conn.execute(
                'SELECT * FROM research_holdout_segments WHERE segment_id=?', (model.segment_id,)
            ).fetchone()
            if row:
                if dict(row) != asdict(model):
                    raise StoreConflict(ConflictKind.IDENTITY_CONFLICT)
                return model
            self.conn.execute(
                'INSERT INTO research_holdout_segments '
                '(segment_id,instrument_id,start_us,end_us,purpose) VALUES (?,?,?,?,?)',
                tuple(asdict(model).values()),
            )
        return model

    def grant_holdout(self, experiment_id: str, segment_id: str,
                      granted_by: str, request_key: str) -> HoldoutGrant:
        request_payload = {'experiment_id': experiment_id, 'segment_id': segment_id}

        def write(server_time_us: int) -> str:
            exp = self.conn.execute(
                'SELECT experiment_type FROM research_experiments WHERE experiment_id=?',
                (experiment_id,),
            ).fetchone()
            if exp is None:
                raise ValueError('unknown experiment')
            if exp[0] not in GRANT_TYPES:
                raise ValueError('holdout grant requires confirmatory or promotion-review experiment')
            if not self.conn.execute(
                'SELECT 1 FROM research_holdout_segments WHERE segment_id=?', (segment_id,)
            ).fetchone():
                raise ValueError('unknown holdout segment')
            effective, _ = self.effective_preregistration(experiment_id)
            model = HoldoutGrant.create(
                experiment_id, segment_id, effective, granted_by, request_key, server_time_us,
            )
            self.conn.execute(
                'INSERT INTO research_holdout_grants '
                '(grant_id,experiment_id,segment_id,effective_prereg_digest,granted_by,request_key,granted_at_us) '
                'VALUES (?,?,?,?,?,?,?)', tuple(asdict(model).values()),
            )
            return model.grant_id

        receipt = self.store.request_write(
            granted_by, 'research.holdout_grant', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_holdout_grants WHERE grant_id=?', (receipt.result_ref,)
        ).fetchone()
        return self._row_model(HoldoutGrant, row)

    def guard_holdout(self, grant_id: str, actor: str, purpose: str, route: str,
                      start_us: int, end_us: int, request_key: str) -> HoldoutPermission:
        if route not in ROUTES:
            raise ValueError('unsupported holdout route')
        request_payload = {
            'grant_id': grant_id, 'purpose': purpose, 'route': route,
            'start_us': start_us, 'end_us': end_us,
        }

        def write(server_time_us: int) -> str:
            row = self.conn.execute(
                'SELECT g.*,s.instrument_id,s.start_us AS segment_start,s.end_us AS segment_end '
                'FROM research_holdout_grants g JOIN research_holdout_segments s ON s.segment_id=g.segment_id '
                'WHERE g.grant_id=?', (grant_id,),
            ).fetchone()
            if row is None:
                raise ValueError('unknown holdout grant')
            current_effective, _ = self.effective_preregistration(row['experiment_id'])
            has_prior = self.conn.execute(
                'SELECT 1 FROM research_exposures WHERE grant_id=? LIMIT 1', (grant_id,)
            ).fetchone() is not None
            if current_effective != row['effective_prereg_digest'] and not has_prior:
                raise ValueError('stale unused holdout grant after preregistration amendment')
            effective = row['effective_prereg_digest']
            sequence = self._sequence_for_digest(row['experiment_id'], effective)
            overlap_start = max(start_us, row['segment_start'])
            overlap_end = min(end_us, row['segment_end'])
            if overlap_start >= overlap_end:
                raise ValueError('requested interval does not overlap protected holdout segment')
            grant = HoldoutGrant(
                row['grant_id'], row['experiment_id'], row['segment_id'],
                row['effective_prereg_digest'], row['granted_by'], row['request_key'],
                row['granted_at_us'],
            )
            model = Exposure.create(
                row['segment_id'], actor, purpose, route, overlap_start, overlap_end,
                grant_id, grant.batch_session_id, effective, sequence,
                self._next_evidence_order(row['experiment_id']), server_time_us,
            )
            self.conn.execute(
                'INSERT INTO research_exposures '
                '(exposure_id,segment_id,actor,purpose,route,start_us,end_us,grant_id,batch_session_id,'
                'effective_prereg_digest,amendment_sequence,evidence_order,served_at_us) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', tuple(asdict(model).values()),
            )
            return model.exposure_id

        receipt = self.store.request_write(
            actor, 'research.holdout_exposure', request_key, request_payload, write,
        )
        row = self.conn.execute(
            'SELECT * FROM research_exposures WHERE exposure_id=?', (receipt.result_ref,)
        ).fetchone()
        if row is None:
            raise RuntimeError('holdout exposure request receipt is inconsistent')
        exposure = self._row_model(Exposure, row)
        return HoldoutPermission(exposure.batch_session_id, (exposure,))

    def seal_state(self, experiment_id: str) -> SealState | None:
        if not self.conn.execute(
            'SELECT 1 FROM research_experiments WHERE experiment_id=?', (experiment_id,)
        ).fetchone():
            raise ValueError('unknown experiment')
        row = self.conn.execute(
            """
            SELECT effective_prereg_digest,amendment_sequence,source,evidence_id,evidence_order,sealed_at_us
            FROM (
              SELECT e.effective_prereg_digest,e.amendment_sequence,'TRIAL_STARTED' AS source,
                     e.event_id AS evidence_id,e.evidence_order,e.recorded_at_us AS sealed_at_us
              FROM research_trial_events e JOIN research_trials t ON t.trial_id=e.trial_id
              WHERE t.experiment_id=? AND e.event='STARTED'
              UNION ALL
              SELECT x.effective_prereg_digest,x.amendment_sequence,'HOLDOUT_EXPOSURE' AS source,
                     x.exposure_id AS evidence_id,x.evidence_order,x.served_at_us AS sealed_at_us
              FROM research_exposures x JOIN research_holdout_grants g ON g.grant_id=x.grant_id
              WHERE g.experiment_id=?
            ) ORDER BY evidence_order,source,evidence_id LIMIT 1
            """, (experiment_id, experiment_id),
        ).fetchone()
        return self._row_model(SealState, row) if row else None

    def holdout_status(self, segment_id: str) -> HoldoutStatus:
        if not self.conn.execute(
            'SELECT 1 FROM research_holdout_segments WHERE segment_id=?', (segment_id,)
        ).fetchone():
            raise ValueError('unknown holdout segment')
        sessions = tuple(
            r[0] for r in self.conn.execute(
                'SELECT DISTINCT batch_session_id FROM research_exposures '
                'WHERE segment_id=? ORDER BY batch_session_id', (segment_id,)
            )
        )
        status = 'UNTOUCHED' if not sessions else ('GRANTED_IN_USE' if len(sessions) == 1 else 'INSPECTED')
        return HoldoutStatus(status, sessions)

    def confirmatory_eligible(self, experiment_id: str) -> bool:
        row = self.conn.execute(
            'SELECT experiment_type FROM research_experiments WHERE experiment_id=?', (experiment_id,)
        ).fetchone()
        if row is None:
            raise ValueError('unknown experiment')
        if row[0] not in GRANT_TYPES:
            return False
        seal = self.seal_state(experiment_id)
        if seal is not None:
            _, current_sequence = self.effective_preregistration(experiment_id)
            if current_sequence > seal.amendment_sequence:
                return False
        segments = self.conn.execute(
            'SELECT DISTINCT segment_id FROM research_holdout_grants WHERE experiment_id=?',
            (experiment_id,),
        )
        return all(self.holdout_status(r[0]).status != 'INSPECTED' for r in segments)
