"""Small storage contracts for the existing run and request tables."""
from dataclasses import dataclass
import json

from atlas2.core.canonical import ace1_encode
from atlas2.core.errors import CanonicalEncodingError
from atlas2.core.time import validate_utc_micros
from atlas2.core.units import validate_int64
from atlas2.model.data import _digest, _text


def _canonical_json(text: str) -> None:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result

    _text(text)
    try:
        parsed = json.loads(text, object_pairs_hook=unique_object)
        canonical = ace1_encode(parsed).decode('utf-8')
    except (json.JSONDecodeError, CanonicalEncodingError) as exc:
        raise ValueError('canonical ACE-1 JSON required') from exc
    if canonical != text:
        raise ValueError('canonical ACE-1 JSON required')


@dataclass(frozen=True)
class RunManifest:
    manifest_id: str
    logical_input_digest: str
    holdout_batch_session_id: str | None
    mode: str
    content_json: str

    def validate(self) -> None:
        _text(self.manifest_id)
        _digest(self.logical_input_digest)
        if self.holdout_batch_session_id is not None:
            _text(self.holdout_batch_session_id)
        if self.mode not in {'REPLAY', 'FORWARD'}:
            raise ValueError('invalid mode')
        _canonical_json(self.content_json)


@dataclass(frozen=True)
class RunAttemptStart:
    attempt_id: str
    manifest_id: str
    recovery_epoch: int
    attempt_no: int
    started_at_us: int
    code_ref_json: str

    def validate(self) -> None:
        _text(self.attempt_id)
        _text(self.manifest_id)
        for value in (self.recovery_epoch, self.attempt_no):
            if validate_int64(value) < 1:
                raise ValueError('positive integer required')
        validate_utc_micros(self.started_at_us)
        _canonical_json(self.code_ref_json)


@dataclass(frozen=True)
class RunAttemptEnd:
    attempt_id: str
    status: str
    replay_digest: str | None
    failure_code: str | None
    ended_at_us: int

    def validate(self) -> None:
        _text(self.attempt_id)
        if self.status not in {'COMPLETED', 'FAILED', 'ABORTED'}:
            raise ValueError('invalid terminal status')
        if self.replay_digest is not None:
            _digest(self.replay_digest)
        if self.failure_code is not None:
            _text(self.failure_code)
        validate_utc_micros(self.ended_at_us)


@dataclass(frozen=True)
class RequestResult:
    actor_id: str
    action_kind: str
    client_key: str
    payload_digest: str
    result_ref: str
    server_time_us: int

    def validate(self) -> None:
        for value in (self.actor_id, self.action_kind, self.client_key, self.result_ref):
            _text(value)
        _digest(self.payload_digest)
        validate_utc_micros(self.server_time_us)
