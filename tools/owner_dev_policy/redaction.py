"""Secret redaction and bounded excerpts for anything that is journaled, exported or displayed."""
from __future__ import annotations

import re

EXCERPT_CHARS = 4000

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key)\b(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|\S+)"),
)


def redact(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 3:
            text = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)
        else:
            text = pattern.sub("[REDACTED]", text)
    return text


def bounded_excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """Redact, then bound. The truncation marker makes a shortened excerpt explicit, never silent."""
    text = redact(text)
    return text if len(text) <= limit else text[:limit] + f"...[truncated {len(text) - limit} chars]"
