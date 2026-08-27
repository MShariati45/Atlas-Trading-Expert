from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from threading import RLock, get_ident
import time
from typing import Any


class InMemoryStateStore:
    """Simple state store used by tests and ephemeral runs."""
    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def get(self, key: str, default=None):
        return deepcopy(self._state.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._state[key] = deepcopy(value)

    def delete(self, key: str) -> None:
        self._state.pop(key, None)


class JsonFileStateStore:
    """Small persistent JSON state store for single-machine demo operation.

    This is intentionally conservative and atomic enough for a single Atlas
    process. Production multi-process deployments should replace it with
    SQLite/Postgres/Redis while preserving the same get/set/delete contract.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if not self.path.exists():
            self._write({})

    def _read(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        # Use a writer-specific temporary file so independent store instances
        # cannot collide on the same fixed .tmp path. os.replace remains atomic.
        tmp = self.path.with_name(
            f"{self.path.name}.{os.getpid()}.{get_ident()}.tmp"
        )
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

        # Windows can transiently deny replacement while antivirus/indexing or
        # another reader has the destination open. Retry boundedly rather than
        # crashing the supervisor on the first sharing violation/access denial.
        delays = (0.05, 0.10, 0.20, 0.40, 0.80, 1.60)
        try:
            for attempt, delay in enumerate(delays, start=1):
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    if attempt == len(delays):
                        raise
                    time.sleep(delay)
        finally:
            # A failed final replace must not leave writer-specific debris.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def get(self, key: str, default=None):
        with self._lock:
            return deepcopy(self._read().get(key, default))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            data = self._read()
            data[key] = deepcopy(value)
            self._write(data)

    def delete(self, key: str) -> None:
        with self._lock:
            data = self._read()
            data.pop(key, None)
            self._write(data)


class NamespacedStateStore:
    """Prefixing adapter so multiple directional M15 runtimes can share storage."""

    def __init__(self, base: Any, namespace: str) -> None:
        self.base = base
        self.namespace = str(namespace).strip(":")

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def get(self, key: str, default=None):
        return self.base.get(self._key(key), default)

    def set(self, key: str, value: Any) -> None:
        self.base.set(self._key(key), value)

    def delete(self, key: str) -> None:
        self.base.delete(self._key(key))
