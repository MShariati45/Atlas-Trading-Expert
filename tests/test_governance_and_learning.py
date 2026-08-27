from pathlib import Path
from tempfile import TemporaryDirectory
import ast

from atlas.governance.roles import ROLE_CONTRACTS
from atlas.research.education_supervisor import ResearchEducationSupervisor, ResearchKnowledgeStore
from atlas.research.trusted_sources import TRUSTED_SOURCES
from atlas.supervisor.runtime import SupervisorContext, SupervisorRuntime
from atlas.strategy.profile import default_m15_first_profile


def test_agent_role_contracts_cover_core_agents():
    expected={"H4_STRUCTURE","H1_STRUCTURE","FIBONACCI","M15_SPECIALISTS","M15_COORDINATOR","SUPERVISOR","RESEARCH_EDUCATION_SUPERVISOR"}
    assert expected <= set(ROLE_CONTRACTS)
    assert "H4_STATE" in ROLE_CONTRACTS["H1_STRUCTURE"].forbidden_inputs
    assert "H1_STATE" in ROLE_CONTRACTS["H4_STRUCTURE"].forbidden_inputs
    assert "SELF_MODIFYING_STRATEGY" in ROLE_CONTRACTS["SUPERVISOR"].forbidden_inputs


def test_specialist_modules_do_not_import_each_other():
    base=Path(__file__).resolve().parents[1]/"atlas"/"agents"
    specialists=[p for p in base.glob("m15_*.py")]
    for path in specialists:
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.module and node.module.startswith("atlas.agents.m15_"):
                assert node.module.endswith(path.stem), f"{path.name} imports another specialist: {node.module}"


def test_research_memory_is_persistent_and_non_mutating():
    with TemporaryDirectory() as d:
        store=ResearchKnowledgeStore(Path(d)/"knowledge.json")
        sup=ResearchEducationSupervisor(store)
        lesson=sup.ingest_verified_lesson(audience=("H4_STRUCTURE",),title="Policy regime note",summary="Higher uncertainty can change volatility regimes.",source_id="BIS_QR",published_at="2026-06-15")
        corr=sup.remember_correction(agent_id="H4_STRUCTURE",rule="Do not inherit H1 trend.",rationale="Timeframe independence rule.")
        packet=ResearchEducationSupervisor(ResearchKnowledgeStore(Path(d)/"knowledge.json")).education_packet("H4_STRUCTURE")
        assert any(x["lesson_id"]==lesson.lesson_id for x in packet["lessons"])
        assert any(x["correction_id"]==corr.correction_id for x in packet["corrections"])
        assert packet["live_rule_mutation_allowed"] is False


def test_trusted_source_registry_uses_https_and_primary_sources():
    ids={s.source_id for s in TRUSTED_SOURCES}
    assert {"FED_MPR","ECB_EB","BOC_MPR","BOJ_MPOL","BIS_QR","IMF_GFSR"} <= ids
    assert all(s.url.startswith("https://") for s in TRUSTED_SOURCES)
    assert all(s.tier in {1,2} for s in TRUSTED_SOURCES)
    assert any(s.tier == 2 for s in TRUSTED_SOURCES)


def test_supervisor_does_not_override_pattern_specific_htf_gate():
    s=SupervisorRuntime.from_strategy_profile(default_m15_first_profile())
    ctx=SupervisorContext(symbol="USDCAD",proposed_risk_pct=.5,day_ok=True,session_ok=True,alignment_ok=True,fib_ok=True,m15_ok=True,freshness_ok=True,static_zone_ok=True,spread_ok=True,news_ok=True,structural_stop_ok=True,net_rr_ok=True,h4_strategic_trend="BULLISH",h1_trend="BULLISH",requested_direction="LONG",pattern_policy_resolved=True)
    rr=s.review(ctx)
    assert rr.gates["alignment_ok"] is True
    assert "PATTERN_SPECIFIC_HTF_POLICY_ACCEPTED" in rr.reason_codes
