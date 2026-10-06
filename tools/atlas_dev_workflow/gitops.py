"""Safe Git worktree management and a pluggable, idempotent merge/PR gateway.

Never cleans, resets, force-pushes or mutates protected branches. Unknown or dirty targets are refused
and left untouched.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .contracts import SHA_RE
from .errors import GitSafetyError
from .policy import PROTECTED_BRANCHES

_FORBIDDEN_GIT = (
    ("reset", "--hard"), ("clean",), ("push", "--force"), ("push", "-f"), ("push", "--force-with-lease"),
    ("checkout", "--force"), ("checkout", "-f"), ("branch", "-D"), ("worktree", "remove", "--force"),
    ("stash",), ("rebase",), ("filter-branch",), ("update-ref", "-d"),
)


def guard_git_args(args: list[str]) -> None:
    for pattern in _FORBIDDEN_GIT:
        if args[: 1] == [pattern[0]] and all(p in args for p in pattern[1:]):
            raise GitSafetyError(f"refused unsafe git operation: git {' '.join(args)}")
    if args[:1] == ["push"]:
        if any(a.startswith("+") for a in args[1:]):
            raise GitSafetyError("refused forced refspec push")
        if any(a.split(":")[-1].removeprefix("refs/heads/") in PROTECTED_BRANCHES for a in args[1:]):
            raise GitSafetyError("refused direct push to protected branch")


def git(args: list[str], cwd: str | Path) -> str:
    guard_git_args(args)
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise GitSafetyError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:500]}")
    return proc.stdout.strip()


class Workspace(Protocol):
    def create(self, task_id: str, branch: str, base_sha: str) -> dict[str, Any]: ...
    def head(self, path: str) -> str: ...
    def is_dirty(self, path: str) -> bool: ...


class WorktreeManager:
    """One task -> one branch -> one worktree, created at an exact base SHA outside the source worktree."""

    def __init__(self, repo_root: str | Path, worktrees_root: str | Path):
        self.repo_root = Path(repo_root).resolve()
        self.worktrees_root = Path(worktrees_root).resolve()
        if self.worktrees_root == self.repo_root or self.repo_root in self.worktrees_root.parents:
            raise GitSafetyError("task worktrees must live outside the current worktree")

    def path_for(self, task_id: str) -> Path:
        return self.worktrees_root / f"devwf-{task_id}"

    def _registered(self) -> dict[str, str | None]:
        out, current = {}, None
        for line in git(["worktree", "list", "--porcelain"], self.repo_root).splitlines():
            if line.startswith("worktree "):
                current = str(Path(line[9:]).resolve())
                out[current] = None
            elif line.startswith("branch ") and current:
                out[current] = line[7:].removeprefix("refs/heads/")
        return out

    def _branch_tip(self, branch: str) -> str | None:
        try:
            return git(["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], self.repo_root)
        except GitSafetyError:
            return None

    def create(self, task_id: str, branch: str, base_sha: str) -> dict[str, Any]:
        if branch in PROTECTED_BRANCHES:
            raise GitSafetyError(f"refused: task branch may not be protected branch {branch}")
        if not SHA_RE.fullmatch(base_sha):
            raise GitSafetyError("base SHA must be an exact 40-hex commit id")
        git(["check-ref-format", "--branch", branch], self.repo_root)
        if git(["rev-parse", "--verify", f"{base_sha}^{{commit}}"], self.repo_root) != base_sha:
            raise GitSafetyError(f"base SHA {base_sha} does not resolve exactly")
        path = self.path_for(task_id)
        registered = self._registered()
        if path.exists() or str(path) in registered:
            if registered.get(str(path)) != branch:
                raise GitSafetyError(f"refused: target {path} exists and is not this task's worktree; left untouched")
            if self.is_dirty(str(path)):
                raise GitSafetyError(f"refused: target worktree {path} is dirty; left untouched")
            return {"path": str(path), "branch": branch, "base_sha": base_sha, "head": self.head(str(path)),
                    "reused": True}
        for wt_path, wt_branch in registered.items():
            if wt_branch == branch:
                raise GitSafetyError(f"refused: branch {branch} already checked out at {wt_path}")
        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        tip = self._branch_tip(branch)
        if tip is None:
            git(["worktree", "add", "-b", branch, str(path), base_sha], self.repo_root)
        elif tip == base_sha:
            git(["worktree", "add", str(path), branch], self.repo_root)
        else:
            raise GitSafetyError(f"refused: branch {branch} exists at {tip}, not base {base_sha}")
        head = self.head(str(path))
        if head != base_sha:
            raise GitSafetyError(f"new worktree head {head} != base {base_sha}")
        return {"path": str(path), "branch": branch, "base_sha": base_sha, "head": head, "reused": False}

    def head(self, path: str) -> str:
        return git(["rev-parse", "HEAD"], path)

    def current_branch(self, path: str) -> str:
        return git(["rev-parse", "--abbrev-ref", "HEAD"], path)

    def is_dirty(self, path: str) -> bool:
        return bool(git(["status", "--porcelain", "--untracked-files=all"], path))

    def is_ancestor(self, ancestor: str, descendant: str) -> bool:
        proc = subprocess.run(["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=str(self.repo_root),
                              capture_output=True, check=False)
        return proc.returncode == 0

    def changed_files(self, base_sha: str, head_sha: str) -> list[str]:
        out = git(["diff", "--name-only", f"{base_sha}..{head_sha}"], self.repo_root)
        return sorted(line for line in out.splitlines() if line)


# --- merge / PR gateway --------------------------------------------------------------------------

class MergeGateway(Protocol):
    def request_merge(self, *, key: str, task_id: str, branch: str, target: str, head_sha: str) -> dict[str, Any]: ...
    def lookup(self, key: str) -> dict[str, Any] | None: ...


@dataclass
class ManualMergeGateway:
    """Default gateway: writes a merge request for the operator; never pushes or merges itself.

    The operator opens/merges the PR by their normal process, then records the result with
    `merge-confirm`, which writes `<key>.confirmed.json` for lookup().
    """
    requests_dir: Path

    def request_merge(self, *, key: str, task_id: str, branch: str, target: str, head_sha: str) -> dict[str, Any]:
        if branch in PROTECTED_BRANCHES:
            raise GitSafetyError("refused direct main mutation: source branch is protected")
        self.requests_dir.mkdir(parents=True, exist_ok=True)
        req = {"key": key, "task_id": task_id, "branch": branch, "target": target, "head_sha": head_sha,
               "method": "pull_request", "force_push": False}
        path = self.requests_dir / f"{key}.json"
        if not path.exists():
            path.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {"status": "REQUESTED", "request_file": str(path)}

    def lookup(self, key: str) -> dict[str, Any] | None:
        path = self.requests_dir / f"{key}.confirmed.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def confirm(self, key: str, *, merged_head: str, source_head: str, merge_ref: str) -> dict[str, Any]:
        if not (self.requests_dir / f"{key}.json").exists():
            raise GitSafetyError(f"no merge request {key}")
        result = {"status": "MERGED", "merged_head": merged_head, "source_head": source_head, "merge_ref": merge_ref}
        (self.requests_dir / f"{key}.confirmed.json").write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        return result


@dataclass
class FakeMergeGateway:
    """Test double: merges instantly and counts real mutations so duplicates are observable."""
    merged: dict[str, dict[str, Any]] = field(default_factory=dict)
    request_count: int = 0
    defer: bool = False

    def request_merge(self, *, key: str, task_id: str, branch: str, target: str, head_sha: str) -> dict[str, Any]:
        self.request_count += 1
        result = {"status": "MERGED", "merged_head": head_sha, "source_head": head_sha, "merge_ref": f"pr/{task_id}"}
        self.merged[key] = result
        return {"status": "REQUESTED"} if self.defer else result

    def lookup(self, key: str) -> dict[str, Any] | None:
        return self.merged.get(key)
