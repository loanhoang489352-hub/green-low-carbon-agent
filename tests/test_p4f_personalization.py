"""
验证 P4-F: 知识库个性化
- F.1: retrieve_knowledge 软过滤(region/interests boost)
- F.2: 知识库按地区有可索引的内容
- F.3: 推荐引擎 augment_with_rag 混合 RAG + ACTION_LIBRARY
"""
import sys
import os
import tempfile
import sqlite3
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_rerank_by_personalization_region():
    """F.1: region 命中的文档分数被提升"""
    from agent.graph.nodes import AgentNodes

    nodes = AgentNodes()
    nodes.initialize()

    # 模拟 3 个结果, 1 个含 region 关键词
    class _R:
        def __init__(self, id, content, score, metadata):
            self.id = id
            self.content = content
            self.score = score
            self.metadata = metadata

    results = [
        _R("1", "national policy", 0.5, {"category": "policy", "source": "national_policy.md"}),
        _R("2", "beijing low carbon", 0.5, {"category": "policy", "source": "beijing_low_carbon.md"}),
        _R("3", "guide content", 0.5, {"category": "guide", "source": "guide.md"}),
    ]
    hints = {"region": "北京", "interests": []}

    ranked = nodes._rerank_by_personalization(results, hints)
    # beijing 那个应排在最前
    assert ranked[0].id == "2", f"期望 beijing 排第一, 实际 {ranked[0].id}"
    print(f"   ranked: {[r.id for r in ranked]}, top score={ranked[0].score:.3f}")
    print("✅ test_rerank_by_personalization_region PASSED")


def test_rerank_by_personalization_interests():
    """F.1: interests 命中的文档分数被提升"""
    from agent.graph.nodes import AgentNodes

    nodes = AgentNodes()
    nodes.initialize()

    class _R:
        def __init__(self, id, content, score, metadata):
            self.id = id
            self.content = content
            self.score = score
            self.metadata = metadata

    results = [
        _R("1", "energy saving tips", 0.5, {"category": "guide", "source": "energy.md"}),
        _R("2", "low carbon travel", 0.5, {"category": "guide", "source": "travel.md"}),
        _R("3", "diet advice", 0.5, {"category": "guide", "source": "diet.md"}),
    ]
    hints = {"region": "全国", "interests": ["low_carbon_travel"]}

    ranked = nodes._rerank_by_personalization(results, hints)
    # low_carbon_travel 应排第一
    assert ranked[0].id == "2", f"期望 travel 排第一, 实际 {ranked[0].id}"
    print(f"   ranked: {[r.id for r in ranked]}")
    print("✅ test_rerank_by_personalization_interests PASSED")


def test_rerank_no_personalization():
    """F.1: 无画像信号时, 不改变原顺序"""
    from agent.graph.nodes import AgentNodes

    nodes = AgentNodes()
    nodes.initialize()

    class _R:
        def __init__(self, id, content, score, metadata):
            self.id = id
            self.content = content
            self.score = score
            self.metadata = metadata

    results = [
        _R("1", "a", 0.9, {}),
        _R("2", "b", 0.5, {}),
    ]
    ranked = nodes._rerank_by_personalization(results, {})
    # 保持原序
    assert [r.id for r in ranked] == ["1", "2"]
    print("✅ test_rerank_no_personalization PASSED")


def test_policy_region_files_exist():
    """F.2: 知识库按地区有可索引的内容"""
    kb_root = Path(__file__).resolve().parent.parent / "knowledge_base" / "policy"
    assert kb_root.exists()
    files = list(kb_root.glob("*.md"))
    assert len(files) >= 2, f"期望至少 2 个政策文件, 实际 {len(files)}"
    # 至少一个含地区标识
    has_region = any("beijing" in f.name.lower() or "shanghai" in f.name.lower()
                     for f in files)
    assert has_region, "应至少有一个地区级政策文件"
    print(f"   policy files: {[f.name for f in files]}")
    print("✅ test_policy_region_files_exist PASSED")


def test_augment_with_rag_adds_policy_rec():
    """F.3: augment_with_rag 在有 RAG 结果时, 头部插入 policy 推荐"""
    from user_profile.personalized_recommender import (
        PersonalizedRecommendationEngine, Recommendation,
    )

    eng = PersonalizedRecommendationEngine()
    static = [
        Recommendation(
            action="骑自行车通勤", category="出行", reason="低排放",
            personalization_context={}, difficulty="easy", impact="medium",
            estimated_carbon_saving="1.5kg/周", examples=[], rejected_reasons=[],
        ),
    ]
    rag = [
        {"content": "北京市大力推广新能源车, 个人碳普惠可累计积分",
         "source": "beijing_low_carbon.md", "score": 0.85},
        {"content": "国六排放标准", "source": "national_policy.md", "score": 0.5},
    ]
    profile = {
        "basic_info": {"region": "北京"},
        "eco_profile": {"primary_interests": ["low_carbon_travel"]},
    }
    result = eng.augment_with_rag(static, profile, rag)
    # 第一个应是 RAG 来的 policy
    assert result[0].category == "policy"
    assert "北京" in result[0].action
    assert result[0].personalization_context.get("source") == "rag"
    print(f"   top rec: {result[0].action}")
    print("✅ test_augment_with_rag_adds_policy_rec PASSED")


def test_augment_with_rag_empty():
    """F.3: 无 RAG 结果时, 直接返回 static 列表"""
    from user_profile.personalized_recommender import (
        PersonalizedRecommendationEngine, Recommendation,
    )

    eng = PersonalizedRecommendationEngine()
    static = [
        Recommendation(
            action="自带购物袋", category="消费", reason="减塑",
            personalization_context={}, difficulty="easy", impact="low",
            estimated_carbon_saving="0.05kg/次", examples=[], rejected_reasons=[],
        ),
    ]
    result = eng.augment_with_rag(static, {}, [])
    assert len(result) == 1
    assert result[0].action == "自带购物袋"
    print("✅ test_augment_with_rag_empty PASSED")


def test_build_personalization_hints():
    """F.1: _build_personalization_hints 从画像提取 region/interests"""
    from agent.graph.nodes import AgentNodes

    nodes = AgentNodes()
    nodes.initialize()

    # 直接 mock 一下 _profile_manager 返回的 profile
    class _MockPM:
        def get_profile(self, uid):
            return {
                "user_id": uid,
                "basic_info": {"region": "上海", "income_level": "高收入"},
                "eco_profile": {"primary_interests": ["waste_classification", "low_carbon_travel"]},
            }

    nodes._profile_manager = _MockPM()

    class _State(dict):
        def get(self, k, default=None):
            return super().get(k, default)
    state = _State(user_id="u_test")
    hints = nodes._build_personalization_hints(state)
    assert hints["region"] == "上海"
    assert "waste_classification" in hints["interests"]
    print(f"   hints: {hints}")
    print("✅ test_build_personalization_hints PASSED")


if __name__ == "__main__":
    test_rerank_by_personalization_region()
    test_rerank_by_personalization_interests()
    test_rerank_no_personalization()
    test_policy_region_files_exist()
    test_augment_with_rag_adds_policy_rec()
    test_augment_with_rag_empty()
    test_build_personalization_hints()
    print("\n🎉 all P4-F personalization tests passed")
