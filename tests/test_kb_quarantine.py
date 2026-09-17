from pathlib import Path

from rag.graphrag import GraphRAGEngine


def test_graphrag_never_loads_quarantine(tmp_path):
    (tmp_path / "guide").mkdir()
    (tmp_path / "_quarantine").mkdir()
    (tmp_path / "guide" / "good.md").write_text(
        "# 公交低碳\n\n在城市日常通勤场景中，合理选择公交出行可以帮助减少碳排放。",
        encoding="utf-8",
    )
    (tmp_path / "_quarantine" / "bad.md").write_text("# 隔离政策\n\n这段隔离内容不应进入图。", encoding="utf-8")
    graph = GraphRAGEngine(str(tmp_path))
    graph.initialize(force_rebuild=True)
    assert "good" in graph.graph
    assert "bad" not in graph.graph


def test_all_rag_load_paths_contain_internal_directory_guard():
    source = (Path(__file__).resolve().parents[1] / "src/rag/rag_engine.py").read_text(encoding="utf-8")
    assert source.count('part.startswith("_")') >= 2
    assert '{"_quarantine", "_versions"}' in source
