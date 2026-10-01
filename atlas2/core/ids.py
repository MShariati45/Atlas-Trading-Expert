from __future__ import annotations

import re
from typing import Any

from .canonical import domain_digest

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_[0-9a-f]{64}$")


def make_id(prefix: str, domain_tag: str, preimage: Any) -> str:
    if type(prefix) is not str or not re.fullmatch(r"[a-z][a-z0-9_]*", prefix):
        raise ValueError("invalid ID prefix")
    ident = f"{prefix}_{domain_digest(domain_tag, preimage)}"
    if not _ID_RE.fullmatch(ident):
        raise ValueError("generated ID does not satisfy Atlas v2 format")
    return ident


def validate_id(value: str, expected_prefix: str | tuple[str, ...] | None = None) -> str:
    if type(value) is not str or not _ID_RE.fullmatch(value):
        raise ValueError("invalid Atlas v2 ID")
    if expected_prefix is not None:
        expected = (expected_prefix,) if type(expected_prefix) is str else expected_prefix
        if type(expected) is not tuple or not expected or any(
            type(prefix) is not str or not re.fullmatch(r"[a-z][a-z0-9_]*", prefix)
            for prefix in expected
        ):
            raise ValueError("invalid expected ID prefix")
        actual = value.rsplit("_", 1)[0]
        if actual not in expected:
            raise ValueError(f"expected ID prefix {expected}, got {actual!r}")
    return value
