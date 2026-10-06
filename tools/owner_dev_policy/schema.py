"""Shared errors, canonical JSON, digests and strict field validators for versioned contracts."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class OwnerPolicyError(Exception):
    """Base error for owner-policy and project development-workflow failures."""


class SchemaError(OwnerPolicyError):
    """A versioned contract, packet, event, projection or control request failed strict validation."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(tag: str, value: Any) -> str:
    return hashlib.sha256((tag + "\x00" + canonical_json(value)).encode("utf-8")).hexdigest()


def obj(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SchemaError(f"{where}: expected object")
    return value


def keys(data: Mapping[str, Any], where: str, required: set[str], optional: set[str] = frozenset()) -> None:
    missing = required - data.keys()
    unknown = data.keys() - required - optional
    if missing:
        raise SchemaError(f"{where}: missing field(s) {sorted(missing)}")
    if unknown:
        raise SchemaError(f"{where}: unknown field(s) {sorted(unknown)}")


def string(value: Any, where: str, *, pattern: re.Pattern[str] | None = None, empty: bool = False) -> str:
    if type(value) is not str or (not empty and not value.strip()):
        raise SchemaError(f"{where}: expected non-empty string")
    if pattern is not None and not pattern.fullmatch(value):
        raise SchemaError(f"{where}: invalid format")
    return value


def optional_string(value: Any, where: str, *, pattern: re.Pattern[str] | None = None) -> str | None:
    return None if value is None else string(value, where, pattern=pattern)


def boolean(value: Any, where: str) -> bool:
    if type(value) is not bool:
        raise SchemaError(f"{where}: expected boolean")
    return value


def integer(value: Any, where: str, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise SchemaError(f"{where}: expected integer in [{lo}, {hi}]")
    return value


def strings(value: Any, where: str, *, allowed: frozenset[str] | None = None, nonempty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(type(v) is not str or not v.strip() for v in value):
        raise SchemaError(f"{where}: expected list of non-empty strings")
    if nonempty and not value:
        raise SchemaError(f"{where}: must not be empty")
    if allowed is not None and (bad := sorted(set(value) - allowed)):
        raise SchemaError(f"{where}: unknown value(s) {bad}")
    return tuple(value)


def choice(value: Any, where: str, choices: tuple[str, ...] | frozenset[str]) -> str:
    if value not in choices:
        raise SchemaError(f"{where}: expected one of {sorted(choices)}")
    return value


def single_action(value: Any, where: str) -> str:
    """Exactly one executable next action: one non-empty line, never a list of options."""
    text = string(value, where)
    if "\n" in text.strip() or len(text) > 500:
        raise SchemaError(f"{where}: must be exactly one action on one line (max 500 chars)")
    return text.strip()
