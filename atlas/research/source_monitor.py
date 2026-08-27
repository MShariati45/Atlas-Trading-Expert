from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from urllib.request import Request, urlopen

from atlas.research.education_supervisor import ResearchKnowledgeStore
from atlas.research.trusted_sources import TRUSTED_SOURCES, TrustedSource

_TITLE_RE=re.compile(r"<title[^>]*>(.*?)</title>",re.I|re.S)
_TAG_RE=re.compile(r"<[^>]+>")
_SPACE_RE=re.compile(r"\s+")

@dataclass(frozen=True, slots=True)
class SourceCheckResult:
    source_id: str
    ok: bool
    changed: bool
    title: str | None
    fingerprint: str | None
    checked_at: str
    error: str | None=None

class TrustedSourceMonitor:
    """Low-cost off-hours source monitor using direct HTTPS, not an AI API.

    It detects changes on authoritative publication landing pages. Changed pages are
    queued for human/optional-AI review; monitoring itself never alters trading rules.
    """
    def __init__(self, store: ResearchKnowledgeStore, timeout_seconds: float=12.0) -> None:
        self.store=store; self.timeout_seconds=timeout_seconds

    @staticmethod
    def _normalize(html: str) -> str:
        text=_TAG_RE.sub(" ",html)
        return _SPACE_RE.sub(" ",text).strip()[:200000]

    def check(self, source: TrustedSource) -> SourceCheckResult:
        now=datetime.now(timezone.utc).isoformat()
        try:
            req=Request(source.url,headers={"User-Agent":"AtlasResearchMonitor/0.23.6 (+read-only publication check)"})
            with urlopen(req,timeout=self.timeout_seconds) as r:
                body=r.read(2_000_000).decode("utf-8",errors="replace")
            norm=self._normalize(body)
            fp=hashlib.sha256(norm.encode("utf-8")).hexdigest()
            title_match=_TITLE_RE.search(body)
            title=_SPACE_RE.sub(" ",title_match.group(1)).strip() if title_match else None
            raw=self.store._read()
            prior=(raw.get("source_checks",{}).get(source.source_id) or {}).get("fingerprint")
            changed=prior is not None and prior != fp
            self.store.record_source_check(source.source_id,fp,now)
            return SourceCheckResult(source.source_id,True,changed,title,fp,now)
        except Exception as exc:
            return SourceCheckResult(source.source_id,False,False,None,None,now,str(exc))

    def check_all(self) -> list[SourceCheckResult]:
        return [self.check(s) for s in TRUSTED_SOURCES]
