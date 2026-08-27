"""Off-hours authoritative-publication monitor. No AI calls; no trading-rule changes."""
from __future__ import annotations
import json
from dataclasses import asdict
from pathlib import Path
from atlas.research.education_supervisor import ResearchKnowledgeStore
from atlas.research.source_monitor import TrustedSourceMonitor


def main() -> int:
    base=Path(__file__).resolve().parent
    store=ResearchKnowledgeStore(base/'runtime'/'research_knowledge.json')
    results=TrustedSourceMonitor(store).check_all()
    print(json.dumps([asdict(x) for x in results],indent=2))
    # Connectivity failure is not a trading failure; this is an off-hours monitor.
    return 0

if __name__=='__main__':
    raise SystemExit(main())
