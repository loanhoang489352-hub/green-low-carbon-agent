"""
P5-G: LTM 向量检索测试

覆盖:
1. 语义搜索:加 4 条记忆(自行车/垃圾分类/新能源/牛肉),搜"环保出行" → 自行车或新能源在 top-3
2. 嵌入为 NULL 的行降级:UPDATE SET embedding=NULL 后搜"植树"仍能命中
3. 无 embedder:不初始化 RAG,add_memory 存 NULL embedding,搜"步行" LIKE 命中
4. 迁移:旧表加 embedding BLOB 列,旧行 NULL
5. 去重:向量和 LIKE 同时命中同一条记录,不应重复

注意:为避免依赖 HuggingFace 网络下载,使用确定性"伪嵌入器"(基于关键词的
共现向量),足以验证 search_memories 的向量召回逻辑。
"""
import sys
import sqlite3
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# 确定性伪嵌入器(避免下载真实模型)
# ---------------------------------------------------------------------------
class FakeEmbedder:
    """基于关键词共现的确定性嵌入器,32 维

    把内容中的关键词映射到固定维度,语义相关词共享维度,模拟"环保出行" 与
    "自行车"/"新能源" 共享 dim,与 "牛肉" 不共享。
    """

    # 维度分配(语义簇):0-3 出行,4-7 食物,8-11 垃圾,12-15 能源,16-31 通用
    _KEYWORD_DIMS = {
        # 出行簇(0-3)
        "出行": [0, 1], "自行车": [0, 2], "通勤": [0, 3], "新能源": [1, 2, 12],
        "汽车": [1, 3], "电动": [1, 12], "公交": [0, 3], "步行": [0, 2],
        "地铁": [0, 3], "环保": [1, 4, 8, 12],
        # 食物簇(4-7)
        "牛肉": [4, 5], "汉堡": [4, 6], "饮食": [4, 7], "餐": [5, 6],
        # 垃圾簇(8-11)
        "垃圾": [8, 9], "分类": [8, 10], "厨余": [8, 11], "处理": [9, 10],
        # 能源簇(12-15)
        "能源": [12, 13], "电": [12, 14], "节能": [13, 14], "光伏": [12, 15],
        # 植树/其他(16-19)
        "植树": [16, 17], "种": [16, 18], "树": [17, 18], "阳台": [17, 19],
        # 碳/家庭(20-23)
        "碳": [20, 21], "家庭": [20, 22], "账单": [22, 23], "排放": [20, 23],
    }
    _DIM = 32

    def encode(self, text):
        """encode(str | list[str]) → np.ndarray"""
        if isinstance(text, str):
            texts = [text]
            single = True
        else:
            texts = list(text)
            single = False

        out = np.zeros((len(texts), self._DIM), dtype="float32")
        for i, t in enumerate(texts):
            for kw, dims in self._KEYWORD_DIMS.items():
                if kw in t:
                    for d in dims:
                        out[i, d] += 1.0
            # L2 归一化(避免长文本主导)
            n = float(np.linalg.norm(out[i]))
            if n > 0:
                out[i] /= n
        return out[0] if single else out


@pytest.fixture
def ltm_with_fake_rag(tmp_path, monkeypatch):
    """LongTermMemory 临时 DB + 假 embedder(无网络)"""
    from rag.rag_engine import get_rag_engine, reset_rag_engine
    import rag.rag_engine as rag_mod

    reset_rag_engine()

    # 直接构造一个 mock 引擎,bypass initialize 网络调用
    class FakeRAGEngine:
        _initialized = True
        _embedder = FakeEmbedder()

    fake_engine = FakeRAGEngine()
    monkeypatch.setattr(rag_mod, "_engine_instance", fake_engine, raising=False)
    monkeypatch.setattr(rag_mod, "get_rag_engine", lambda config=None: fake_engine)

    # 也要 patch long_term 里的 get_rag_engine(它是 from import 进来的)
    import memory.long_term as ltm_mod
    # long_term 里是 from rag.rag_engine import get_rag_engine,在函数内部用,
    # 所以这里 monkeypatch 模块属性即可
    # 但实际上 _compute_embedding_blob 是 from rag.rag_engine import get_rag_engine
    # 在函数内部 import,所以会拿到我们 patch 后的版本

    from memory.long_term import LongTermMemory
    db = tmp_path / "ltm_vec.db"
    ltm = LongTermMemory(str(db))
    yield ltm

    reset_rag_engine()


def test_search_by_semantic_similarity(ltm_with_fake_rag):
    """语义搜索:加 4 条不同主题记忆,搜"环保出行" 召回相关"""
    ltm = ltm_with_fake_rag
    ltm.add_memory("u1", "我喜欢骑自行车通勤,每周能省 5 公斤碳", importance=0.7)
    ltm.add_memory("u1", "我对垃圾分类很感兴趣,尤其是厨余处理", importance=0.6)
    ltm.add_memory("u1", "我刚买了新能源汽车,打算跑长途测试", importance=0.5)
    ltm.add_memory("u1", "今天吃了牛肉汉堡,挺好吃", importance=0.3)

    results = ltm.search_memories("u1", "环保出行", limit=3)
    assert len(results) >= 1
    contents = [r["content"] for r in results]
    # 自行车或新能源应被召回(语义相关)
    assert any("自行车" in c or "新能源" in c for c in contents), \
        f"语义召回失败,实际 top-3: {contents}"


def test_search_falls_back_to_like_when_embedding_is_null(ltm_with_fake_rag, tmp_path):
    """某行 embedding 为 NULL:向量跳过,LIKE 仍能命中"""
    ltm = ltm_with_fake_rag
    ltm.add_memory("u1", "我喜欢植树,家里阳台种了 3 棵", importance=0.6)

    # 手动把 embedding 设为 NULL(模拟迁移前的旧行)
    conn = sqlite3.connect(str(ltm.db_path))
    conn.execute("UPDATE user_memories SET embedding=NULL")
    conn.commit()
    conn.close()

    from memory.long_term import LongTermMemory
    ltm2 = LongTermMemory(str(ltm.db_path))
    results = ltm2.search_memories("u1", "植树", limit=5)
    assert len(results) == 1
    assert "植树" in results[0]["content"]


def test_search_works_without_embedder(tmp_path):
    """embedder 不可用:add_memory 存 NULL embedding,搜"步行" LIKE 命中"""
    # 不设置任何 fake engine,reset 让 get_rag_engine 返 None
    from rag.rag_engine import reset_rag_engine
    reset_rag_engine()

    from memory.long_term import LongTermMemory

    db = tmp_path / "ltm_norag.db"
    ltm = LongTermMemory(str(db))
    ltm.add_memory("u1", "用户喜欢步行上班,每天 30 分钟", importance=0.6)
    ltm.add_memory("u1", "用户关注碳排放数据", importance=0.5)

    # embedder 不可用 → embedding 应存 NULL
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT embedding FROM user_memories WHERE user_id='u1'").fetchone()
    conn.close()
    assert row[0] is None, "embedder 不可用时,embedding 列应存 NULL"

    # 搜索仍能用 LIKE 命中
    results = ltm.search_memories("u1", "步行", limit=5)
    assert len(results) == 1
    assert "步行" in results[0]["content"]


def test_migration_adds_embedding_column(tmp_path):
    """P5-G: 旧表(无 embedding 列)被 LongTermMemory._init_database 自动 ALTER 加列"""
    db = tmp_path / "ltm_old.db"

    # 1) 手工建一个不含 embedding 的旧表 + 一行旧数据
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE user_memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT, memory_type TEXT, content TEXT,
            importance REAL, created_at TEXT, last_accessed TEXT,
            access_count INTEGER, tags TEXT
        )
    """)
    conn.execute("""
        INSERT INTO user_memories
        (user_id, memory_type, content, importance, created_at, last_accessed)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("u1", "general", "迁移前数据", 0.5, "2025-01-01T00:00:00", "2025-01-01T00:00:00"))
    conn.commit()
    conn.close()

    # 2) 实例化 LongTermMemory,触发 _init_database 的迁移逻辑
    from memory.long_term import LongTermMemory
    LongTermMemory(str(db))

    # 3) 验证
    conn = sqlite3.connect(str(db))
    cols = [r[1] for r in conn.execute("PRAGMA table_info(user_memories)").fetchall()]
    assert "embedding" in cols, f"embedding 列未加,实际列: {cols}"
    # 旧行 embedding 应为 NULL
    row = conn.execute("SELECT embedding FROM user_memories").fetchone()
    assert row[0] is None
    conn.close()


def test_search_dedup_vector_and_like(ltm_with_fake_rag):
    """向量和 LIKE 同时命中的同一条记录,不应重复出现在结果中"""
    ltm = ltm_with_fake_rag
    # 这条内容同时包含 query 子串(触发 LIKE)和语义相关(触发向量)
    ltm.add_memory("u1", "我喜欢环保出行,坐地铁通勤", importance=0.7)
    ltm.add_memory("u1", "我关心家庭碳足迹,每月看账单", importance=0.5)

    results = ltm.search_memories("u1", "环保出行", limit=10)
    # 同一条记忆不应被计 2 次
    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)), f"去重失败,ids={ids}"
    # 第一条应该是高度相关的"环保出行"
    assert "环保出行" in results[0]["content"] or "地铁" in results[0]["content"]
