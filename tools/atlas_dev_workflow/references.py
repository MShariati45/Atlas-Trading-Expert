"""Deterministic project reference registry (lightweight lexical index, no vector DB, no network)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping

INDEX_VERSION = "atlas-devwf.references.v1"

# (kind, glob relative to repo root)
DEFAULT_SOURCES: tuple[tuple[str, str], ...] = (
    ("atlas2_contract", "docs/atlas2/*.md"),
    ("atlas2_contract", "docs/atlas2/adr/*.md"),
    ("atlas2_code", "atlas2/**/*.py"),
    ("atlas2_tests", "tests/atlas2/*.py"),
    ("dev_workflow", "tools/atlas_dev_workflow/*.md"),
    ("dev_workflow", "tools/owner_dev_policy/*.md"),
)
RESEARCH_TAGS = {"research": "experiment_registry", "holdout": "holdout", "taint": "taint",
                 "replay": "replay", "registry": "experiment_registry", "labels": "labels",
                 "capture": "candidate_capture", "time": "point_in_time", "htf": "point_in_time"}
LEGACY_SOURCES: tuple[tuple[str, str], ...] = (("legacy_handoff", "*HANDOFF*.md"), ("legacy_handoff", "*Handoff*.md"))
_TOKEN = re.compile(r"[a-z0-9]+")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _title(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for _, line in zip(range(40), fh):
                s = line.strip()
                if s.startswith("#") or (s.startswith('"""') and len(s) > 3):
                    return s.strip('#" ').strip()[:160]
    except OSError:
        pass
    return path.stem


def _tags(rel: str) -> list[str]:
    return sorted({tag for key, tag in RESEARCH_TAGS.items() if key in rel.lower()})


def _entry(kind: str, rel: str, sha: str | None, size: int | None, title: str, tags: list[str], **extra: Any) -> dict[str, Any]:
    ref_id = "ref_" + hashlib.sha256(f"{kind}\x00{rel}".encode()).hexdigest()[:16]
    return {"ref_id": ref_id, "kind": kind, "path": rel, "sha256": sha, "bytes": size, "title": title,
            "tags": tags, **extra}


def build_index(repo_root: str | Path, *, external_refs: Iterable[Mapping[str, str]] = (),
                include_legacy: bool = True, git_log_limit: int = 50,
                evidence_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    entries: list[dict[str, Any]] = []
    sources = DEFAULT_SOURCES + (LEGACY_SOURCES if include_legacy else ())
    seen = set()
    for kind, pattern in sources:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or (kind, rel) in seen or "__pycache__" in rel:
                continue
            seen.add((kind, rel))
            entries.append(_entry(kind, rel, _sha256_file(path), path.stat().st_size, _title(path), _tags(rel)))
    for ref in external_refs:
        path = Path(ref["path"]).expanduser()
        try:
            actual = _sha256_file(path) if path.is_file() else None
            status = "missing" if actual is None else ("verified" if actual == ref.get("sha256") else "hash_mismatch")
        except OSError as exc:  # e.g. a cloud-synced or permission-protected file; never fatal
            actual, status = None, f"unreadable: {type(exc).__name__}"
        entries.append(_entry("design_reference", str(path), actual, path.stat().st_size if actual else None,
                              ref.get("title", path.name), ["design"], expected_sha256=ref.get("sha256"), status=status))
    if evidence_dir is not None and Path(evidence_dir).is_dir():
        for path in sorted(Path(evidence_dir).glob("*.json")):
            entries.append(_entry("task_evidence", path.name, _sha256_file(path), path.stat().st_size, path.stem, ["evidence"]))
    head = None
    if git_log_limit > 0:
        proc = subprocess.run(["git", "log", f"-n{git_log_limit}", "--format=%H%x09%s"], cwd=str(root),
                              capture_output=True, text=True, check=False)
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                sha, _, subject = line.partition("\t")
                head = head or sha
                entries.append(_entry("git_commit", sha, sha, None, subject[:160], _tags(subject)))
    entries.sort(key=lambda e: (e["kind"], e["path"]))
    return {"schema_version": INDEX_VERSION, "repo_head": head, "entry_count": len(entries), "entries": entries}


def save_index(index: Mapping[str, Any], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load_index(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def query(index: Mapping[str, Any], text: str, *, limit: int = 8, include_legacy: bool = False,
          kinds: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Lexical scoring over path/title/tags. Legacy handoffs only when explicitly requested."""
    tokens = set(_TOKEN.findall(text.lower()))
    allowed = set(kinds) if kinds else None
    scored = []
    for entry in index.get("entries", []):
        if entry["kind"] == "legacy_handoff" and not include_legacy:
            continue
        if allowed is not None and entry["kind"] not in allowed:
            continue
        hay = set(_TOKEN.findall(f"{entry['path']} {entry['title']} {' '.join(entry['tags'])}".lower()))
        score = len(tokens & hay)
        if score:
            scored.append((-score, entry["kind"], entry["path"], entry))
    scored.sort(key=lambda s: s[:3])
    return [dict(s[3], score=-s[0]) for s in scored[:limit]]
