from pathlib import Path


def test_both_agent_paths_put_evidence_grade_and_usage_limit_in_prompt():
    root = Path(__file__).resolve().parents[1]
    core = (root / "src/agent/core.py").read_text(encoding="utf-8")
    nodes = (root / "src/agent/graph/nodes.py").read_text(encoding="utf-8")
    for source in (core, nodes):
        assert "evidence_status" in source
        assert "不可据此断言具体数值、政策或标准" in source
        assert "source_url" in source


def test_knowledge_stats_exposes_governance_audit():
    root = Path(__file__).resolve().parents[1]
    system_router = (root / "src/server/routers/system.py").read_text(encoding="utf-8")
    assert 'stats["governance"]' in system_router
    assert "traceability_rate" in system_router
