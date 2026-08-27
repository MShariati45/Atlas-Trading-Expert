from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from atlas.research.trusted_sources import TRUSTED_SOURCES

@dataclass(frozen=True, slots=True)
class Lesson:
    lesson_id: str
    audience: tuple[str, ...]
    title: str
    summary: str
    source_id: str
    source_url: str
    published_at: str | None
    verified_at: str
    evidence_hash: str
    status: str = "ACTIVE"

@dataclass(frozen=True, slots=True)
class Correction:
    correction_id: str
    agent_id: str
    rule: str
    rationale: str
    created_at: str
    status: str = "ACTIVE"
    requires_revalidation: bool = True

class ResearchKnowledgeStore:
    """Persistent research/lesson/correction memory for a single Atlas node.

    Knowledge is advisory. It cannot mutate strategy/profile code or live agent state.
    A lesson/correction becomes a trading-rule change only through explicit code/profile
    promotion plus regression/backtest validation.
    """
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({"lessons": {}, "corrections": {}, "source_checks": {}})

    def _read(self) -> dict[str, Any]:
        try:
            raw=json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            raw={}
        raw.setdefault("lessons",{}); raw.setdefault("corrections",{}); raw.setdefault("source_checks",{})
        return raw

    def _write(self, raw: dict[str, Any]) -> None:
        tmp=self.path.with_suffix(self.path.suffix+".tmp")
        tmp.write_text(json.dumps(raw,indent=2,sort_keys=True),encoding="utf-8")
        tmp.replace(self.path)

    def add_lesson(self, lesson: Lesson) -> None:
        raw=self._read(); raw["lessons"][lesson.lesson_id]=asdict(lesson); self._write(raw)

    def add_correction(self, correction: Correction) -> None:
        raw=self._read(); raw["corrections"][correction.correction_id]=asdict(correction); self._write(raw)

    def lessons_for(self, agent_id: str) -> list[dict[str, Any]]:
        raw=self._read()
        return [x for x in raw["lessons"].values() if x.get("status")=="ACTIVE" and (agent_id in x.get("audience",[]) or "ALL" in x.get("audience",[]))]

    def corrections_for(self, agent_id: str) -> list[dict[str, Any]]:
        raw=self._read()
        return [x for x in raw["corrections"].values() if x.get("status")=="ACTIVE" and x.get("agent_id") in {agent_id,"ALL"}]

    def record_source_check(self, source_id: str, fingerprint: str, checked_at: str | None=None) -> None:
        raw=self._read(); raw["source_checks"][source_id]={"fingerprint":fingerprint,"checked_at":checked_at or datetime.now(timezone.utc).isoformat()}; self._write(raw)

class ResearchEducationSupervisor:
    """Governed education layer.

    This component maintains trusted sources and persistent lessons/corrections.
    It never calls trading agents directly and never changes their state. Optional
    network/AI workers may prepare lessons off-hours, but promotion to strategy
    logic is always explicit and validated.
    """
    def __init__(self, store: ResearchKnowledgeStore) -> None:
        self.store=store
        self.sources={s.source_id:s for s in TRUSTED_SOURCES}

    def ingest_verified_lesson(self, *, audience: tuple[str,...], title: str, summary: str, source_id: str, published_at: str | None=None, evidence: str="") -> Lesson:
        if source_id not in self.sources:
            raise ValueError("UNTRUSTED_SOURCE")
        src=self.sources[source_id]
        verified_at=datetime.now(timezone.utc).isoformat()
        digest=hashlib.sha256((source_id+"|"+title+"|"+summary+"|"+evidence).encode("utf-8")).hexdigest()
        lesson=Lesson(digest[:24], audience, title, summary, source_id, src.url, published_at, verified_at, digest)
        self.store.add_lesson(lesson)
        return lesson

    def remember_correction(self, *, agent_id: str, rule: str, rationale: str) -> Correction:
        created=datetime.now(timezone.utc).isoformat()
        digest=hashlib.sha256((agent_id+"|"+rule+"|"+rationale).encode("utf-8")).hexdigest()
        correction=Correction(digest[:24], agent_id, rule, rationale, created)
        self.store.add_correction(correction)
        return correction

    def education_packet(self, agent_id: str) -> dict[str, Any]:
        return {
            "agent_id":agent_id,
            "lessons":self.store.lessons_for(agent_id),
            "corrections":self.store.corrections_for(agent_id),
            "live_rule_mutation_allowed":False,
            "promotion_required":"EXPLICIT_VALIDATED_PROFILE_OR_CODE_CHANGE",
        }
