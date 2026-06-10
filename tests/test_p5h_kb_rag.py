"""
P5-H: 知识库合并 + ChromaDB 持久化测试

覆盖:
A. ChromaDB Windows 持久化:重启后 collection 仍在 + 计数不丢
B. KnowledgeManager 代理化:RAGEngine 可用时走 retrieve(),不可用降级 + warning
C. 异步重建:rebuild_index_async 立刻返回,get_rebuild_status 可查进度
D. 分块 hash:同前缀不同尾段 → hash 不同;大文档走 SHA256
E. 增量 upsert:add_documents / delete_documents 按 source 增删
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import pytest


# ---------------------------------------------------------------------------
# 共用:FakeEmbedder + FakeRAGEngine(避免触网下载真实模型)
# ---------------------------------------------------------------------------
import numpy as np


class _FakeEmbedder:
    """32 维确定性嵌入器"""
    _DIM = 32

    def encode(self, text):
        if isinstance(text, str):
            texts = [text]
            single = True
        else:
            texts = list(text)
            single = False
        out = np.zeros((len(texts), self._DIM), dtype="float32")
        for i, t in enumerate(texts):
            for ch in t[:200]:
                out[i, ord(ch) % self._DIM] += 1.0
            n = float(np.linalg.norm(out[i]))
            if n > 0:
                out[i] /= n
        return out[0] if single else out


# ---------------------------------------------------------------------------
# P5-H.A: ChromaDB 持久化
# ---------------------------------------------------------------------------
def test_chroma_persistent_client_used_on_windows(tmp_path):
    """ChromaStore 在 Windows 上也应使用 PersistentClient(P5-H.A 修复)"""
    from rag.vector_store import ChromaStore
    store = ChromaStore(
        persist_directory=str(tmp_path / "chroma"),
        collection_name="test_persist",
    )
    # 客户端应初始化(可能降级)
    assert store._client is not None, "ChromaDB 应初始化(可能降级 EphemeralClient)"
    # P5-H.A: 显式持久化标志应为 True(chromadb 1.5+ 在 Windows 也支持 PersistentClient)
    assert store.is_persistent, (
        "Windows 下应使用 PersistentClient,而非降级到 EphemeralClient"
    )
    # 持久化目录应创建
    assert (tmp_path / "chroma").is_dir()


def test_chroma_persistence_across_instances(tmp_path):
    """加文档 → 删实例 → 新建实例 → 文档仍在(P5-H.A 核心)"""
    from rag.vector_store import ChromaStore, Document
    import numpy as np

    persist_dir = tmp_path / "chroma_persist"
    s1 = ChromaStore(persist_directory=str(persist_dir), collection_name="t_persist")

    # 若降级为 EphemeralClient,跳过(降级路径本身就不持久,P5-H.A 主目标
    # 是 PersistentClient 的尝试路径)
    if not s1.is_persistent:
        pytest.skip("PersistentClient 初始化失败,跳过持久化测试")

    docs = [
        Document(id="d1", content="test1", metadata={"src": "a"},
                 embedding=np.array([0.1] * 32, dtype="float32")),
        Document(id="d2", content="test2", metadata={"src": "b"},
                 embedding=np.array([0.2] * 32, dtype="float32")),
    ]
    s1.add(docs)
    assert s1.count() == 2

    # 销毁 + 重建
    del s1
    s2 = ChromaStore(persist_directory=str(persist_dir), collection_name="t_persist")
    assert s2.count() == 2, "重建后文档丢失,持久化未生效"


# ---------------------------------------------------------------------------
# P5-H.B: KnowledgeManager 代理化
# ---------------------------------------------------------------------------
def test_knowledge_manager_delegates_to_rag_engine(tmp_path, monkeypatch):
    """RAGEngine 可用时,KnowledgeManager.search() 应优先用 retrieve()"""
    # 准备最小知识库
    kb = tmp_path / "kb"
    (kb / "test").mkdir(parents=True)
    (kb / "test" / "x.md").write_text("# 测试\n碳中和内容", encoding="utf-8")

    # 准备 fake engine
    class FakeRetrievalResult:
        def __init__(self, id, content, metadata, score):
            self.id = id
            self.content = content
            self.metadata = metadata
            self.score = score

    class FakeEngine:
        _initialized = True

        def retrieve(self, query, top_k=5):
            return [
                FakeRetrievalResult(
                    id="rag-1",
                    content="RAG 返回的内容",
                    metadata={"source": "test/x.md", "category": "test"},
                    score=0.95,
                ),
            ]

    import rag.rag_engine as rag_mod
    monkeypatch.setattr(rag_mod, "get_rag_engine", lambda config=None: FakeEngine())

    from knowledge.manager import KnowledgeManager
    km = KnowledgeManager(str(kb))
    results = km.search("碳中和", top_k=3)
    assert len(results) >= 1
    assert results[0]["id"] == "rag-1"
    assert results[0]["title"] == "x"
    assert "RAG" in results[0]["content"]


def test_knowledge_manager_falls_back_with_warning(tmp_path, monkeypatch):
    """RAGEngine 不可用时,降级关键词搜索并发 DeprecationWarning"""
    import rag.rag_engine as rag_mod
    monkeypatch.setattr(rag_mod, "get_rag_engine", lambda config=None: None)

    kb = tmp_path / "kb"
    (kb / "basic").mkdir(parents=True)
    (kb / "basic" / "carbon.md").write_text(
        "# 碳中和\n碳中和是关键概念,涉及碳排放与节能", encoding="utf-8"
    )

    from knowledge.manager import KnowledgeManager
    km = KnowledgeManager(str(kb))

    with pytest.warns(DeprecationWarning, match="rag.rag_engine.get_rag_engine"):
        results = km.search("碳中和", top_k=3)
    assert len(results) >= 1
    assert "碳中和" in results[0]["title"] or "碳中和" in results[0]["content"]


# ---------------------------------------------------------------------------
# P5-H.C: 异步重建
# ---------------------------------------------------------------------------
def test_rebuild_index_async_returns_immediately(tmp_path, monkeypatch):
    """rebuild_index_async 应立刻返回 running 状态,然后后台跑完"""
    # 用真实 RAGEngine,但注入 fake embedder
    from rag.rag_engine import RAGEngine, RAGConfig
    from rag.retriever import HybridRetriever

    persist_dir = tmp_path / "chroma_async"
    engine = RAGEngine(RAGConfig(
        persist_directory=str(persist_dir),
        collection_name="t_async",
        hybrid_search=False,  # 简化
    ))
    # 手动注入 embedder 跳过模型下载
    from rag.vector_store import ChromaStore
    from rag.retriever import SemanticRetriever
    engine._embedder = _FakeEmbedder()
    engine._embedder._dimension = 32
    engine._vector_store = ChromaStore(
        persist_directory=str(persist_dir),
        collection_name="t_async",
    )
    engine._retriever = SemanticRetriever(
        vector_store=engine._vector_store,
        embedder=engine._embedder,
    )
    engine._initialized = True

    # 准备最小 KB
    kb = tmp_path / "kb"
    (kb / "basic").mkdir(parents=True)
    (kb / "basic" / "a.md").write_text("# A\n碳中和入门", encoding="utf-8")
    (kb / "basic" / "b.md").write_text("# B\n节能减排建议", encoding="utf-8")

    # 启动异步
    state = engine.rebuild_index_async(str(kb))
    assert state["state"] == "running", f"初次调用应为 running,实际 {state}"

    # 等待最多 10s 跑完
    for _ in range(100):
        status = engine.get_rebuild_status()
        if status["state"] in ("done", "error"):
            break
        time.sleep(0.1)

    final = engine.get_rebuild_status()
    assert final["state"] == "done", f"最终状态应为 done,实际 {final}"
    assert final["progress"] == 100
    assert final["total"] >= 2


def test_rebuild_index_async_idempotent_while_running(tmp_path, monkeypatch):
    """已在 running 状态,再次调不会起第二个 worker(返回当前状态)"""
    from rag.rag_engine import RAGEngine, RAGConfig
    engine = RAGEngine(RAGConfig(persist_directory=str(tmp_path / "x")))
    # 强制设为 running
    engine._rebuild_state = {"state": "running", "progress": 50}
    result = engine.rebuild_index_async(str(tmp_path))
    assert result["state"] == "running"
    assert result["progress"] == 50


# ---------------------------------------------------------------------------
# P5-H.D: 分块 hash
# ---------------------------------------------------------------------------
def test_compute_content_hash_detects_tail_changes():
    """同前缀,中段/尾段变化 → hash 不同(P5-H.D 修旧 md5[:20000] 漏检)"""
    from knowledge.updater import KnowledgeUpdater
    prefix = "A" * 100 + "\n\n"
    para_v1 = prefix + "前面正常的政策内容...\n\n变化前的尾段"
    para_v2 = prefix + "前面正常的政策内容...\n\n变化后的尾段"

    h1 = KnowledgeUpdater._compute_content_hash(para_v1)
    h2 = KnowledgeUpdater._compute_content_hash(para_v2)
    assert h1 != h2, "尾段变化应改变 hash"


def test_compute_content_hash_large_uses_sha256():
    """>=50KB 走 SHA256 整文"""
    from knowledge.updater import KnowledgeUpdater
    big = ("ABCDEF\n\n" * 7000)  # 大约 56KB
    h = KnowledgeUpdater._compute_content_hash(big)
    assert h.startswith("sha256:"), f"大文档应走 SHA256,实际 {h[:20]}"


def test_compute_content_hash_small_uses_chunked_md5():
    """<50KB 多段落走分块 md5(更稳定)"""
    from knowledge.updater import KnowledgeUpdater
    small = "段落一\n\n段落二\n\n段落三"
    h = KnowledgeUpdater._compute_content_hash(small)
    assert h.startswith("md5:")


def test_compute_content_hash_empty():
    from knowledge.updater import KnowledgeUpdater
    assert KnowledgeUpdater._compute_content_hash("") == ""


# ---------------------------------------------------------------------------
# P5-H.E: 增量 upsert
# ---------------------------------------------------------------------------
def test_add_documents_increments_count(tmp_path):
    """add_documents([file]) → count 增加,可被 retrieve 到"""
    from rag.rag_engine import RAGEngine, RAGConfig
    from rag.vector_store import ChromaStore
    from rag.retriever import SemanticRetriever

    engine = RAGEngine(RAGConfig(
        persist_directory=str(tmp_path / "x"),
        collection_name="t_incr",
        hybrid_search=False,
    ))
    engine._embedder = _FakeEmbedder()
    engine._embedder._dimension = 32
    engine._vector_store = ChromaStore(
        persist_directory=str(tmp_path / "x"),
        collection_name="t_incr",
    )
    engine._retriever = SemanticRetriever(
        vector_store=engine._vector_store,
        embedder=engine._embedder,
    )
    engine._initialized = True

    kb = tmp_path / "kb"
    kb.mkdir()
    f1 = kb / "doc1.md"
    f1.write_text("# 增量1\n第一份新增文档", encoding="utf-8")
    f2 = kb / "doc2.md"
    f2.write_text("# 增量2\n第二份新增文档", encoding="utf-8")

    n1 = engine.add_documents([str(f1)], base_path=str(kb))
    assert n1 >= 1
    n2 = engine.add_documents([str(f2)], base_path=str(kb))
    assert n2 >= 1
    assert engine._vector_store.count() >= 2


def test_delete_documents_by_source(tmp_path):
    """delete_documents([source]) → 该 source 的所有 chunk 被删"""
    from rag.rag_engine import RAGEngine, RAGConfig
    from rag.vector_store import ChromaStore
    from rag.retriever import SemanticRetriever

    engine = RAGEngine(RAGConfig(
        persist_directory=str(tmp_path / "y"),
        collection_name="t_del",
        hybrid_search=False,
    ))
    engine._embedder = _FakeEmbedder()
    engine._embedder._dimension = 32
    engine._vector_store = ChromaStore(
        persist_directory=str(tmp_path / "y"),
        collection_name="t_del",
    )
    engine._retriever = SemanticRetriever(
        vector_store=engine._vector_store,
        embedder=engine._embedder,
    )
    engine._initialized = True

    kb = tmp_path / "kb"
    kb.mkdir()
    f1 = kb / "keep.md"
    f1.write_text("# 保留\n要保留", encoding="utf-8")
    f2 = kb / "drop.md"
    f2.write_text("# 删除\n要删除", encoding="utf-8")

    engine.add_documents([str(f1), str(f2)], base_path=str(kb))
    before = engine._vector_store.count()
    assert before >= 2

    # 删 drop.md(三种形式都应工作:full path / relative / stem)
    deleted = engine.delete_documents(["drop.md"])
    assert deleted >= 1
    after = engine._vector_store.count()
    assert after == before - deleted


def test_norm_source_handles_variants():
    """_norm_source: 路径 / 文件名 / stem 都归一到 stem"""
    from rag.rag_engine import RAGEngine
    assert RAGEngine._norm_source("policy/xxx.md") == "xxx"
    assert RAGEngine._norm_source("policy\\xxx.md") == "xxx"
    assert RAGEngine._norm_source("xxx.md") == "xxx"
    assert RAGEngine._norm_source("xxx") == "xxx"
    assert RAGEngine._norm_source("") == ""
