"""Runtime configuration and state-directory layout (mutable state lives outside tracked code)."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.owner_dev_policy.monitoring import CONTROL_ACTIONS
from tools.owner_dev_policy.policy import OwnerDevelopmentPolicy
from tools.owner_dev_policy.providers import default_executors, default_role_chains, validate_role_chains
from tools.owner_dev_policy.schema import keys, obj, strings

from .errors import ContractError
from .project import DEFAULT_CONTROL_AUTHORITY, PROJECT_ID
from .roles import AGENT_ROLES

CONFIG_V1 = "atlas-devwf.config.v1"
STATE_DIR_ENV = "ATLAS_DEV_WORKFLOW_HOME"
DEFAULT_STATE_DIRNAME = ".atlas-dev-workflow"
DESIGN_PDF = {
    "path": "/Users/alishaariati/Desktop/Atlas Trading/Atlas v2 Lean Implementation Design v2.pdf",
    "sha256": "8f684e894cb68c5dbbd67f50e290a29cbafbcaca516d609b462dc6f110f8f601",
    "title": "Atlas v2 Lean Implementation Design v2",
}


def repo_root(start: str | Path | None = None) -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(start or Path.cwd()),
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ContractError("not inside a git repository")
    return Path(proc.stdout.strip()).resolve()


_CONFIG_KEYS = {"schema_version", "project_id", "repo_root", "worktrees_root", "lease_ttl_s", "merge_gateway",
                "owner_policy", "executors", "role_chains", "control_authority", "external_refs"}


def default_config(root: Path) -> dict[str, Any]:
    """Real CLI executors ship disabled; the Owner enables them explicitly for authorized local use."""
    owner_policy = OwnerDevelopmentPolicy().to_dict()
    owner_policy.pop("version")
    return {
        "schema_version": CONFIG_V1,
        "project_id": PROJECT_ID,
        "repo_root": str(root),
        "worktrees_root": str(root.parent / "atlas-devwf-worktrees"),
        "lease_ttl_s": 1800,
        "merge_gateway": "manual",
        "owner_policy": owner_policy,
        "executors": default_executors(),
        "role_chains": default_role_chains(),
        "control_authority": DEFAULT_CONTROL_AUTHORITY,
        "external_refs": [DESIGN_PDF],
    }


def validate_config(data: Any) -> dict[str, Any]:
    cfg = obj(data, "config")
    keys(cfg, "config", _CONFIG_KEYS)
    if cfg["schema_version"] != CONFIG_V1:
        raise ContractError(f"unsupported config schema {cfg['schema_version']!r}")
    if cfg["project_id"] != PROJECT_ID:
        raise ContractError(f"config.project_id {cfg['project_id']!r} is not this project ({PROJECT_ID})")
    OwnerDevelopmentPolicy.from_dict(cfg["owner_policy"])
    validate_role_chains(cfg["executors"], cfg["role_chains"], AGENT_ROLES)
    authority = obj(cfg["control_authority"], "config.control_authority")
    keys(authority, "config.control_authority", set(CONTROL_ACTIONS))
    for action, actors in authority.items():
        strings(actors, f"config.control_authority.{action}")
    return dict(cfg)


@dataclass(frozen=True)
class Layout:
    state_dir: Path

    @property
    def db(self) -> Path:
        return self.state_dir / "state.sqlite3"

    @property
    def config(self) -> Path:
        return self.state_dir / "config.json"

    @property
    def references(self) -> Path:
        return self.state_dir / "references.json"

    @property
    def merge_requests(self) -> Path:
        return self.state_dir / "merge_requests"

    @property
    def evidence(self) -> Path:
        return self.state_dir / "evidence"

    @property
    def exports(self) -> Path:
        return self.state_dir / "exports"


def resolve_layout(state_dir: str | None, root: Path) -> Layout:
    chosen = state_dir or os.environ.get(STATE_DIR_ENV) or str(root / DEFAULT_STATE_DIRNAME)
    return Layout(Path(chosen).expanduser().resolve())


def load_config(layout: Layout) -> dict[str, Any]:
    if not layout.config.exists():
        raise ContractError(f"no config at {layout.config}; run `init` first")
    return validate_config(json.loads(layout.config.read_text(encoding="utf-8")))


def write_config(layout: Layout, data: dict[str, Any]) -> None:
    layout.state_dir.mkdir(parents=True, exist_ok=True)
    layout.config.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
