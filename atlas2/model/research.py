"""Frozen research-registry and holdout evidence contracts for Atlas v2 P0-3."""
from __future__ import annotations

from dataclasses import dataclass
import json

from atlas2.core.canonical import ace1_encode, domain_digest
from atlas2.core.errors import CanonicalEncodingError
from atlas2.core.ids import make_id
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64
from atlas2.model.data import _digest, _instrument, _text

TRIAL_EVENTS = frozenset({
    'PLANNED', 'STARTED', 'FAILED', 'ABANDONED',
    'COMPLETED', 'INSPECTED', 'SELECTED', 'REPLICATED',
})
ROUTES = frozenset({'MARKET_VIEW', 'OUTCOME_VIEW', 'LABEL_TASK', 'EXPORT'})
GRANT_TYPES = frozenset({'CONFIRMATORY', 'PROMOTION_REVIEW'})
EXPERIMENT_TYPES = GRANT_TYPES | {'EXPLORATORY', 'LABEL_STUDY', 'ENGINEERING'}
RESULT_KINDS = frozenset({'PRIMARY', 'REPLICATION'})


def canonical_payload(payload: object) -> str:
    return ace1_encode(payload).decode('utf-8')


def validate_canonical_payload(text: str) -> str:
    if type(text) is not str or not text:
        raise ValueError('canonical payload text required')

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    try:
        parsed = json.loads(text, object_pairs_hook=unique_object)
        encoded = canonical_payload(parsed)
    except (json.JSONDecodeError, CanonicalEncodingError) as exc:
        raise ValueError('canonical ACE-1 JSON required') from exc
    if encoded != text:
        raise ValueError('canonical ACE-1 JSON required')
    return text


@dataclass(frozen=True, slots=True)
class Preregistration:
    prereg_digest: str
    payload_json: str

    @classmethod
    def from_payload(cls, payload: dict) -> 'Preregistration':
        if type(payload) is not dict:
            raise ValueError('preregistration payload must be an object')
        if {'prereg_digest', 'prereg_id', 'experiment_id'} & set(payload):
            raise ValueError('identity fields do not belong in preregistration payload')
        text = canonical_payload(payload)
        model = cls(domain_digest('preregistration-v1', payload), text)
        model.validate()
        return model

    def validate(self) -> None:
        _digest(self.prereg_digest)
        validate_canonical_payload(self.payload_json)
        parsed = json.loads(self.payload_json)
        if type(parsed) is not dict:
            raise ValueError('preregistration payload must be an object')
        if self.prereg_digest != domain_digest('preregistration-v1', parsed):
            raise ValueError('preregistration digest mismatch')


@dataclass(frozen=True, slots=True)
class Experiment:
    experiment_id: str
    prereg_digest: str
    registered_by: str
    request_key: str
    experiment_type: str
    registered_at_us: int

    @classmethod
    def create(cls, prereg_digest: str, registered_by: str, request_key: str,
               experiment_type: str, registered_at_us: int) -> 'Experiment':
        model = cls(
            make_id('exp', 'experiment-v1', [prereg_digest, registered_by, request_key]),
            prereg_digest, registered_by, request_key, experiment_type, registered_at_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.experiment_id)
        _digest(self.prereg_digest)
        _text(self.registered_by)
        _text(self.request_key)
        if self.experiment_type not in EXPERIMENT_TYPES:
            raise ValueError('invalid experiment type')
        validate_utc_micros(self.registered_at_us)
        expected = make_id('exp', 'experiment-v1', [self.prereg_digest, self.registered_by, self.request_key])
        if self.experiment_id != expected:
            raise ValueError('experiment identity mismatch')


@dataclass(frozen=True, slots=True)
class Amendment:
    amendment_id: str
    experiment_id: str
    sequence: int
    parent_effective_digest: str
    new_payload_digest: str
    recorded_at_us: int

    @classmethod
    def create(cls, experiment_id: str, sequence: int, parent_effective_digest: str,
               new_payload_digest: str, recorded_at_us: int) -> 'Amendment':
        model = cls(
            make_id('amd', 'amendment-v1', [
                experiment_id, sequence, parent_effective_digest, new_payload_digest,
            ]),
            experiment_id, sequence, parent_effective_digest, new_payload_digest, recorded_at_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.amendment_id)
        _text(self.experiment_id)
        if validate_int64(self.sequence) < 1:
            raise ValueError('amendment sequence must be positive')
        _digest(self.parent_effective_digest)
        _digest(self.new_payload_digest)
        validate_utc_micros(self.recorded_at_us)
        expected = make_id('amd', 'amendment-v1', [
            self.experiment_id, self.sequence, self.parent_effective_digest, self.new_payload_digest,
        ])
        if self.amendment_id != expected:
            raise ValueError('amendment identity mismatch')


@dataclass(frozen=True, slots=True)
class Trial:
    trial_id: str
    experiment_id: str
    trial_index: int
    parameters_json: str

    @classmethod
    def create(cls, experiment_id: str, trial_index: int, parameters: object) -> 'Trial':
        text = canonical_payload(parameters)
        model = cls(
            make_id('trial', 'trial-v1', [experiment_id, trial_index, text]),
            experiment_id, trial_index, text,
        )
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.trial_id)
        _text(self.experiment_id)
        if validate_int64(self.trial_index) < 1:
            raise ValueError('trial index must be positive')
        validate_canonical_payload(self.parameters_json)
        expected = make_id('trial', 'trial-v1', [
            self.experiment_id, self.trial_index, self.parameters_json,
        ])
        if self.trial_id != expected:
            raise ValueError('trial identity mismatch')


@dataclass(frozen=True, slots=True)
class TrialEvent:
    event_id: str
    trial_id: str
    event: str
    effective_prereg_digest: str
    amendment_sequence: int
    evidence_order: int
    recorded_at_us: int

    @classmethod
    def create(cls, trial_id: str, event: str, effective_prereg_digest: str,
               amendment_sequence: int, evidence_order: int, recorded_at_us: int) -> 'TrialEvent':
        model = cls(
            make_id('tev', 'trial-event-v1', [
                trial_id, event, effective_prereg_digest, amendment_sequence, evidence_order,
            ]),
            trial_id, event, effective_prereg_digest, amendment_sequence, evidence_order, recorded_at_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.event_id)
        _text(self.trial_id)
        if self.event not in TRIAL_EVENTS:
            raise ValueError('invalid trial event')
        _digest(self.effective_prereg_digest)
        if validate_int64(self.amendment_sequence) < 0:
            raise ValueError('amendment sequence cannot be negative')
        if validate_int64(self.evidence_order) < 1:
            raise ValueError('evidence order must be positive')
        validate_utc_micros(self.recorded_at_us)
        expected = make_id('tev', 'trial-event-v1', [
            self.trial_id, self.event, self.effective_prereg_digest,
            self.amendment_sequence, self.evidence_order,
        ])
        if self.event_id != expected:
            raise ValueError('trial-event identity mismatch')


@dataclass(frozen=True, slots=True)
class TrialResult:
    result_id: str
    trial_id: str
    result_kind: str
    attempt_id: str
    effective_prereg_digest: str
    payload_json: str
    recorded_at_us: int

    @classmethod
    def create(cls, trial_id: str, result_kind: str, attempt_id: str,
               effective_prereg_digest: str, payload: object, recorded_at_us: int) -> 'TrialResult':
        text = canonical_payload(payload)
        model = cls(
            make_id('tres', 'trial-result-v1', [
                trial_id, result_kind, attempt_id, effective_prereg_digest,
            ]),
            trial_id, result_kind, attempt_id, effective_prereg_digest, text, recorded_at_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.result_id); _text(self.trial_id); _text(self.attempt_id)
        if self.result_kind not in RESULT_KINDS:
            raise ValueError('invalid result kind')
        _digest(self.effective_prereg_digest)
        validate_canonical_payload(self.payload_json)
        validate_utc_micros(self.recorded_at_us)
        expected = make_id('tres', 'trial-result-v1', [
            self.trial_id, self.result_kind, self.attempt_id, self.effective_prereg_digest,
        ])
        if self.result_id != expected:
            raise ValueError('trial-result identity mismatch')


@dataclass(frozen=True, slots=True)
class Decision:
    decision_id: str
    experiment_id: str
    payload_json: str
    recorded_at_us: int

    @classmethod
    def create(cls, experiment_id: str, payload: object, recorded_at_us: int) -> 'Decision':
        text = canonical_payload(payload)
        model = cls(make_id('dec', 'decision-v1', [experiment_id]), experiment_id, text, recorded_at_us)
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.decision_id); _text(self.experiment_id)
        validate_canonical_payload(self.payload_json)
        validate_utc_micros(self.recorded_at_us)
        if self.decision_id != make_id('dec', 'decision-v1', [self.experiment_id]):
            raise ValueError('decision identity mismatch')


@dataclass(frozen=True, slots=True)
class HoldoutSegment:
    segment_id: str
    instrument_id: str
    start_us: int
    end_us: int
    purpose: str = 'FINAL_OOS'

    @classmethod
    def create(cls, instrument_id: str, start_us: int, end_us: int) -> 'HoldoutSegment':
        model = cls(
            make_id('hseg', 'holdout-segment-v1', [instrument_id, start_us, end_us, 'FINAL_OOS']),
            instrument_id, start_us, end_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        _text(self.segment_id)
        validate_interval(self.instrument_id, self.start_us, self.end_us)
        if self.purpose != 'FINAL_OOS':
            raise ValueError('P0-3 supports FINAL_OOS only')
        expected = make_id('hseg', 'holdout-segment-v1', [
            self.instrument_id, self.start_us, self.end_us, self.purpose,
        ])
        if self.segment_id != expected:
            raise ValueError('holdout-segment identity mismatch')


def validate_interval(instrument_id: str, start_us: int, end_us: int) -> None:
    _instrument(instrument_id)
    validate_utc_micros(start_us)
    validate_utc_micros(end_us)
    if start_us >= end_us:
        raise ValueError('nonempty half-open interval required')


@dataclass(frozen=True, slots=True)
class HoldoutGrant:
    grant_id: str
    experiment_id: str
    segment_id: str
    effective_prereg_digest: str
    granted_by: str
    request_key: str
    granted_at_us: int

    @classmethod
    def create(cls, experiment_id: str, segment_id: str, effective_prereg_digest: str,
               granted_by: str, request_key: str, granted_at_us: int) -> 'HoldoutGrant':
        model = cls(
            make_id('hgrant', 'holdout-grant-v1', [
                experiment_id, segment_id, effective_prereg_digest, granted_by, request_key,
            ]),
            experiment_id, segment_id, effective_prereg_digest, granted_by, request_key, granted_at_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        for value in (self.grant_id, self.experiment_id, self.segment_id, self.granted_by, self.request_key):
            _text(value)
        _digest(self.effective_prereg_digest)
        validate_utc_micros(self.granted_at_us)
        expected = make_id('hgrant', 'holdout-grant-v1', [
            self.experiment_id, self.segment_id, self.effective_prereg_digest,
            self.granted_by, self.request_key,
        ])
        if self.grant_id != expected:
            raise ValueError('holdout-grant identity mismatch')

    @property
    def batch_session_id(self) -> str:
        return make_id('hbatch', 'holdout-batch-session-v1', [
            self.grant_id, self.effective_prereg_digest,
        ])


@dataclass(frozen=True, slots=True)
class Exposure:
    exposure_id: str
    segment_id: str
    actor: str
    purpose: str
    route: str
    start_us: int
    end_us: int
    grant_id: str
    batch_session_id: str
    effective_prereg_digest: str
    amendment_sequence: int
    evidence_order: int
    served_at_us: int

    @classmethod
    def create(cls, segment_id: str, actor: str, purpose: str, route: str,
               start_us: int, end_us: int, grant_id: str, batch_session_id: str,
               effective_prereg_digest: str, amendment_sequence: int,
               evidence_order: int, served_at_us: int) -> 'Exposure':
        model = cls(
            make_id('hexp', 'holdout-exposure-v1', [
                segment_id, actor, purpose, route, start_us, end_us, grant_id,
                batch_session_id, effective_prereg_digest, amendment_sequence, evidence_order,
            ]),
            segment_id, actor, purpose, route, start_us, end_us, grant_id,
            batch_session_id, effective_prereg_digest, amendment_sequence,
            evidence_order, served_at_us,
        )
        model.validate()
        return model

    def validate(self) -> None:
        for value in (self.exposure_id, self.segment_id, self.actor, self.purpose,
                      self.grant_id, self.batch_session_id):
            _text(value)
        if self.route not in ROUTES:
            raise ValueError('unsupported holdout route')
        validate_utc_micros(self.start_us); validate_utc_micros(self.end_us)
        if self.start_us >= self.end_us:
            raise ValueError('nonempty half-open interval required')
        _digest(self.effective_prereg_digest)
        if validate_int64(self.amendment_sequence) < 0:
            raise ValueError('amendment sequence cannot be negative')
        if validate_int64(self.evidence_order) < 1:
            raise ValueError('evidence order must be positive')
        validate_utc_micros(self.served_at_us)
        expected = make_id('hexp', 'holdout-exposure-v1', [
            self.segment_id, self.actor, self.purpose, self.route,
            self.start_us, self.end_us, self.grant_id, self.batch_session_id,
            self.effective_prereg_digest, self.amendment_sequence, self.evidence_order,
        ])
        if self.exposure_id != expected:
            raise ValueError('exposure identity mismatch')


@dataclass(frozen=True, slots=True)
class SealState:
    effective_prereg_digest: str
    amendment_sequence: int
    source: str
    evidence_id: str
    evidence_order: int
    sealed_at_us: int


@dataclass(frozen=True, slots=True)
class HoldoutStatus:
    status: str
    batch_session_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HoldoutPermission:
    batch_session_id: str
    exposures: tuple[Exposure, ...]
