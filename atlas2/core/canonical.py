from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

from .errors import CanonicalEncodingError

INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1
_MAX_DEPTH = 16
_MAX_BYTES = 64 * 1024


def _norm_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    for ch in value:
        cp = ord(ch)
        if cp <= 0x1F or 0xD800 <= cp <= 0xDFFF:
            raise CanonicalEncodingError("control characters and lone surrogates are forbidden")
    return value


def _encode_string(value: str) -> bytes:
    value = _norm_text(value)
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return ('"' + escaped + '"').encode("utf-8")


def _encode(value: Any, depth: int) -> bytes:
    if value is None:
        return b"null"
    if type(value) is bool:
        return b"true" if value else b"false"
    if type(value) is int:
        if not INT64_MIN <= value <= INT64_MAX:
            raise CanonicalEncodingError("integer outside int64 range")
        return str(value).encode("ascii")
    if type(value) is float:
        raise CanonicalEncodingError("floats are forbidden")
    if type(value) is str:
        return _encode_string(value)
    if type(value) is list:
        if depth >= _MAX_DEPTH:
            raise CanonicalEncodingError("maximum container nesting depth exceeded")
        return b"[" + b",".join(_encode(item, depth + 1) for item in value) + b"]"
    if type(value) is dict:
        if depth >= _MAX_DEPTH:
            raise CanonicalEncodingError("maximum container nesting depth exceeded")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise CanonicalEncodingError("object keys must be strings")
            if not key.isascii():
                raise CanonicalEncodingError("schema keys must be ASCII")
            nk = _norm_text(key)
            if nk in normalized:
                raise CanonicalEncodingError("duplicate key after normalization")
            normalized[nk] = item
        parts = []
        for key in sorted(normalized, key=lambda k: k.encode("ascii")):
            parts.append(_encode_string(key) + b":" + _encode(normalized[key], depth + 1))
        return b"{" + b",".join(parts) + b"}"
    raise CanonicalEncodingError(f"unsupported type: {type(value).__name__}")


def ace1_encode(value: Any) -> bytes:
    encoded = _encode(value, 0)
    if len(encoded) > _MAX_BYTES:
        raise CanonicalEncodingError("canonical record exceeds 64 KiB")
    return encoded


def domain_digest(domain_tag: str, value: Any) -> str:
    if type(domain_tag) is not str or not domain_tag or not domain_tag.isascii():
        raise CanonicalEncodingError("domain tag must be non-empty ASCII")
    _norm_text(domain_tag)
    payload = b"ATLAS2\x00" + domain_tag.encode("ascii") + b"\x00" + ace1_encode(value)
    return hashlib.sha256(payload).hexdigest()
