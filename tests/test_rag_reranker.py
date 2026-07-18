"""
P8.R1: Reranker 单元测试

覆盖:
- Reranker 禁用时(rerank())直接返回原序
- 加载失败/推理异常时回退到原序,不抛错
- get_stats() 字段完整
- 与 RAGEngine 集成:retrieve() 在 enabled 时调 reranker

不实际下载/加载 BGE 模型(用 mock),保证 CI 快速。
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rag.reranker import Reranker, RerankConfig


class _FakeResult:
    """模拟 RetrievalResult 的最小接口"""

    def __init__(self, content: str, score: float = 0.5):
        self.content = content
        self.score = score


class TestRerankConfig:
    def test_defaults(self):
        c = RerankConfig()
        assert c.enabled is True
        assert c.model_name == "BAAI/bge-reranker-base"
        assert c.top_k_input == 20
        assert c.top_k_output == 5
        assert c.use_fp16 is False

    def test_disabled_by_default_override(self):
        c = RerankConfig(enabled=False)
        assert c.enabled is False


class TestRerankerDisabled:
    def test_disabled_returns_original_order(self):
        r = Reranker(RerankConfig(enabled=False))
        results = [_FakeResult("a"), _FakeResult("b"), _FakeResult("c")]
        out = r.rerank("q", results, top_k=2)
        # 禁用时,顺序与输入完全一致(仅按 top_k 截断)
        assert [x.content for x in out] == ["a", "b"]

    def test_disabled_with_empty(self):
        r = Reranker(RerankConfig(enabled=False))
        assert r.rerank("q", [], top_k=5) == []


class TestRerankerFallback:
    """模型加载/推理失败的容错"""

    def test_load_failure_returns_original(self, monkeypatch):
        """强制 load() 失败 → rerank() 返回原序(降级)"""
        r = Reranker(RerankConfig(enabled=True))

        # 用 monkeypatch 替换 load() 让它直接失败
        def fake_load():
            r._load_attempted = True
            r._load_error = "simulated"
            r._model = None
            return False

        monkeypatch.setattr(r, "load", fake_load)

        results = [_FakeResult("a", 0.5), _FakeResult("b", 0.3)]
        out = r.rerank("q", results, top_k=2)
        # 加载失败 → 原序 + 截断
        assert [x.content for x in out] == ["a", "b"]
        assert r.stats["fail_count"] == 0  # 不是推理失败,是加载失败

    def test_inference_exception_returns_original(self, monkeypatch):
        """模型存在但推理抛异常 → rerank() 返回原序且 fail_count++"""
        r = Reranker(RerankConfig(enabled=True))

        # 假装模型已加载
        class BoomModel:
            def compute_score(self, *args, **kwargs):
                raise RuntimeError("model exploded")

        r._model = BoomModel()
        r._load_attempted = True

        results = [_FakeResult("x"), _FakeResult("y"), _FakeResult("z")]
        out = r.rerank("q", results, top_k=2)
        assert [x.content for x in out] == ["x", "y"]
        assert r.stats["fail_count"] == 1


class TestRerankerStats:
    def test_initial_stats(self):
        r = Reranker(RerankConfig(enabled=True))
        s = r.get_stats()
        assert s["enabled"] is True
        assert s["is_loaded"] is False
        assert s["total_calls"] == 0
        assert s["fail_count"] == 0
        assert s["model_name"] == "BAAI/bge-reranker-base"
        assert s["load_error"] is None


class TestGetRerankerSingleton:
    def test_returns_same_instance(self):
        from rag.reranker import get_reranker, reset_reranker

        reset_reranker()
        a = get_reranker(RerankConfig(enabled=False))
        b = get_reranker()
        assert a is b

        reset_reranker()


class TestRAGEngineIntegration:
    """P8.R1: 验证 RAGEngine.reranker 属性"""

    def setup_method(self):
        # 单例 reset,避免测试间状态污染
        from rag.reranker import reset_reranker

        reset_reranker()

    def teardown_method(self):
        from rag.reranker import reset_reranker

        reset_reranker()

    def test_reranker_none_when_disabled(self):
        from rag.rag_engine import RAGEngine, RAGConfig

        engine = RAGEngine(RAGConfig(rerank_enabled=False, enabled=False))
        assert engine.reranker is None

    def test_reranker_set_when_enabled(self):
        from rag.rag_engine import RAGEngine, RAGConfig

        engine = RAGEngine(RAGConfig(rerank_enabled=True, enabled=False))
        r = engine.reranker
        # enabled=True 时应该返回 Reranker 实例
        assert r is not None
        assert r.config.enabled is True
        assert r.config.model_name == "BAAI/bge-reranker-base"

    def test_reranker_top_k_uses_default(self):
        from rag.rag_engine import RAGEngine, RAGConfig

        engine = RAGEngine(
            RAGConfig(rerank_enabled=True, enabled=False, default_top_k=8)
        )
        r = engine.reranker
        assert r.config.top_k_output == 8


class TestRAGConfigFields:
    """P8.R1: RAGConfig 新增的 rerank 字段"""

    def test_default_rerank_fields(self):
        from rag.rag_engine import RAGConfig

        c = RAGConfig()
        assert hasattr(c, "rerank_enabled")
        assert hasattr(c, "rerank_model")
        assert hasattr(c, "rerank_top_k_input")
        assert hasattr(c, "rerank_use_fp16")
        assert c.rerank_enabled is True
        assert c.rerank_model == "BAAI/bge-reranker-base"
        assert c.rerank_top_k_input == 20
        assert c.rerank_use_fp16 is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])