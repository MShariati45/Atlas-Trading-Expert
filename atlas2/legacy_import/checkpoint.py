"""Read-only legacy file checkpoint helpers. No legacy code execution."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FileCheckpoint:
    status: str
    path: str
    sha256: str | None
    byte_size: int | None
    reason: str | None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def checkpoint_file(path: str | Path, expected_sha256: str | None = None) -> FileCheckpoint:
    target = Path(path)
    if not target.is_file():
        return FileCheckpoint("NOT_VERIFIED", str(target), None, None, "SOURCE_NOT_PRESENT")
    digest = sha256_file(target)
    size = target.stat().st_size
    if expected_sha256 is not None and digest != expected_sha256:
        return FileCheckpoint("NOT_VERIFIED", str(target), digest, size, "HASH_MISMATCH")
    return FileCheckpoint("VERIFIED_HASH", str(target), digest, size, None)
