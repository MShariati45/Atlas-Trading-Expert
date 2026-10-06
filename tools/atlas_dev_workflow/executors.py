"""Pluggable agent executors.

Executors only turn a Handoff into raw text. Packet validation and every state decision happen in
the supervisor. Qualification uses FakeExecutor; CliExecutor exists for later authorized local use
and is never invoked by tests against a real (paid) provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence

from tools.owner_dev_policy import providers
from tools.owner_dev_policy.compute import sanitize_usage
from tools.owner_dev_policy.redaction import bounded_excerpt

from .contracts import canonical_json
from .errors import ContractError, ProviderError, ProviderExhausted
from .roles import AGENT_ROLES, IMPLEMENTER, REVIEWER

MAX_OUTPUT_BYTES = 256 * 1024
KNOWN_CLIS = ("claude", "codex", "gemini")
# Unverified argv templates for local CLIs; the prompt (instructions + handoff JSON) is sent on stdin.
CLI_TEMPLATES: dict[str, list[str]] = {
    "claude": ["claude", "-p", "--model", "{model}"],
    "codex": ["codex", "exec", "--model", "{model}", "-"],
    "gemini": ["gemini", "--model", "{model}", "--prompt", ""],
}
_ENV_ALLOW = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "USER", "SHELL", "TERM")

def output_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def extract_packet(text: str) -> dict[str, Any]:
    """Parse the agent's JSON packet: the whole output, or the last ```json fenced block."""
    candidates = [text.strip()]
    candidates += [m.strip() for m in reversed(re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S))]
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(value, dict):
            return value
    raise ContractError("agent output contains no JSON packet object")


@dataclass(frozen=True)
class ExecResult:
    text: str
    truncated: bool = False  # output was cut at MAX_OUTPUT_BYTES; never treated as a complete packet
    usage: dict[str, int] | None = None  # only provider-reported, sanitized metrics


class AgentExecutor(Protocol):
    kind: str
    provider: str
    model: str

    @property
    def executor_id(self) -> str: ...

    def run(self, handoff: Mapping[str, Any]) -> ExecResult: ...


@dataclass
class FakeExecutor:
    """Deterministic synthetic executor: `responder(handoff)` returns a packet dict, text, or raises."""
    provider: str
    model: str
    responder: Callable[[Mapping[str, Any]], Any]
    kind: str = "fake"
    usage: dict[str, Any] | None = None
    calls: list[str] = field(default_factory=list)
    handoffs: list[dict[str, Any]] = field(default_factory=list)

    @property
    def executor_id(self) -> str:
        return f"{self.kind}:{self.provider}:{self.model}"

    def run(self, handoff: Mapping[str, Any]) -> ExecResult:
        self.calls.append(handoff["step_key"])
        self.handoffs.append(json.loads(canonical_json(dict(handoff))))
        out = self.responder(handoff)
        if isinstance(out, BaseException):
            raise out
        return ExecResult(out if isinstance(out, str) else canonical_json(out), usage=sanitize_usage(self.usage))


@dataclass
class CliExecutor:
    """Runs a locally installed agent CLI with a scrubbed environment, bounded time and output."""
    provider: str
    model: str
    argv: list[str]
    timeout_s: int = 1800
    cwd: str | None = None
    kind: str = "cli"

    @property
    def executor_id(self) -> str:
        return f"{self.kind}:{self.provider}:{self.model}"

    def _env(self) -> dict[str, str]:
        return {k: os.environ[k] for k in _ENV_ALLOW if k in os.environ}

    def run(self, handoff: Mapping[str, Any]) -> ExecResult:
        argv = list(self.argv)
        if self.model == "default" and "{model}" in argv:  # let the CLI use its own configured default
            i = argv.index("{model}")
            del argv[i - 1: i + 1]
        argv = [a.replace("{model}", self.model) for a in argv]
        if not argv or shutil.which(argv[0]) is None and not os.path.isfile(argv[0]):
            raise ProviderError(f"executable not found: {argv[:1]}")
        prompt = handoff["instructions"] + "\n\nHANDOFF JSON:\n" + canonical_json(dict(handoff))
        cwd = handoff.get("workdir") or self.cwd
        try:
            proc = subprocess.run(argv, input=prompt.encode(), capture_output=True, timeout=self.timeout_s,
                                  cwd=cwd, env=self._env(), check=False)
        except subprocess.TimeoutExpired:
            raise ProviderError(f"{self.provider} timed out after {self.timeout_s}s") from None
        except OSError as exc:
            raise ProviderError(f"{self.provider} failed to start: {exc}") from None
        out = proc.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", "replace")
        if proc.returncode != 0:
            err = proc.stderr[:2000].decode("utf-8", "replace")
            error = ProviderExhausted if providers.is_exhaustion(err + out[-2000:]) else ProviderError
            raise error(f"{self.provider} exited {proc.returncode}: {bounded_excerpt(err)}")
        # Local CLIs do not report usage in a stable machine-readable form; usage stays unknown (None).
        return ExecResult(out, truncated=len(proc.stdout) > MAX_OUTPUT_BYTES)


def build_executor(spec: Mapping[str, Any]) -> AgentExecutor:
    kind = spec.get("kind")
    if kind == "cli":
        if not spec.get("enabled", False):
            raise ContractError(f"cli executor {spec.get('provider')} is not enabled in runtime config "
                                "(a disabled executor fails closed; the chain does not skip it silently)")
        argv = list(spec.get("argv") or CLI_TEMPLATES.get(spec.get("provider", ""), []))
        return CliExecutor(provider=spec["provider"], model=spec.get("model", "default"), argv=argv,
                           timeout_s=int(spec.get("timeout_s", 1800)), cwd=spec.get("cwd"))
    raise ContractError(f"unsupported executor kind {kind!r} (use 'cli' or inject a FakeExecutor)")


Binding = AgentExecutor | Sequence[AgentExecutor]


def as_chains(bindings: Mapping[str, Binding]) -> dict[str, list[AgentExecutor]]:
    """Normalize role bindings to ordered failover chains (a single executor is a one-element chain)."""
    return {role: list(b) if isinstance(b, (list, tuple)) else [b] for role, b in bindings.items()}


def validate_bindings(bindings: Mapping[str, Binding], *, independence: str) -> dict[str, list[AgentExecutor]]:
    """All agent roles bound; whichever implementer works, an independent reviewer exists in the chain."""
    chains = as_chains(bindings)
    missing = [r for r in AGENT_ROLES if not chains.get(r)]
    if missing:
        raise ContractError(f"no executor bound for role(s) {missing}")
    providers.validate_chain_independence(chains[IMPLEMENTER], chains[REVIEWER], independence)
    return chains


def build_chains(config: Mapping[str, Any]) -> dict[str, list[AgentExecutor]]:
    """Validate executor specs/qualification and build each role's chain from config (no code constants)."""
    providers.validate_role_chains(config["executors"], config["role_chains"], AGENT_ROLES)
    return {role: [build_executor(config["executors"][name]) for name in config["role_chains"][role]]
            for role in AGENT_ROLES}


def discover_clis(*, probe_version: bool = False, names: tuple[str, ...] = KNOWN_CLIS) -> list[dict[str, Any]]:
    """Find installed agent CLIs on PATH. Never installs anything; version probe is local-only."""
    found = []
    for name in names:
        path = shutil.which(name)
        entry: dict[str, Any] = {"name": name, "path": path, "installed": path is not None,
                                 "argv_template": CLI_TEMPLATES.get(name), "template_verified": False}
        if path and probe_version:
            try:
                proc = subprocess.run([path, "--version"], capture_output=True, timeout=20, check=False)
                entry["version"] = proc.stdout.decode("utf-8", "replace").strip().splitlines()[0][:120]
            except (OSError, subprocess.TimeoutExpired, IndexError):
                entry["version"] = None
        found.append(entry)
    return found
