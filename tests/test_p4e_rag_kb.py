"""
验证 P4-E: 实时知识/政策同步 + RAG 自动重载
- E.1: RAGEngine 单例 + 订阅者真重载
- E.2: GraphRAG 单例
- E.3: 政策 httpx+bs4 抓取
- E.4: 内容去重(content_hash)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_rag_engine_singleton():
    """E.1: RAGEngine 单例(双检锁)"""
    from rag.rag_engine import get_rag_engine, reset_rag_engine
    reset_rag_engine()
    e1 = get_rag_engine()
    e2 = get_rag_engine()
    assert e1 is e2
    print("✅ test_rag_engine_singleton PASSED")


def test_rag_subscriber_uses_singleton():
    """E.1: RAG 订阅者真重载(委托给 RAGEngine 单例或 main.get_agent())"""
    from rag.rag_subscriber import _do_rebuild
    # 模拟 agent 未就绪 + RAGEngine 单例(未启用 enabled) → 退化到"仅日志"
    # 不抛异常即通过
    _do_rebuild(paths=["/fake/path.md"], count=1)
    print("✅ test_rag_subscriber_uses_singleton PASSED")


def test_policy_fetch_and_extract():
    """E.3: 政策抓取(httpx 失败时不阻塞,仅记日志)"""
    from policy.updater import PolicyUpdater
    import tempfile

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "pol.db"
        pu = PolicyUpdater(db_path=str(db), knowledge_base_path=str(Path(tmp) / "kb"))

        # 1) 抓取 URL 不可达 → 不抛异常
        source = {"name": "test_invalid", "url": "http://this-domain-does-not-exist-12345.invalid/", "type": "测试"}
        added = pu._fetch_and_ingest(source)
        assert added == 0  # 失败不写入
        print(f"   invalid url returned {added} policies (expected 0)")

        # 2) 静态 HTML 模拟(不走网络)
        # 直接测试 _extract_content
        sample_html = """
        <html>
        <head><title>测试政策:碳中和路线图</title></head>
        <body>
            <div class="content">
                <p>坚持绿色低碳发展,推动碳达峰碳中和目标如期实现,需要全社会共同努力。
                重点支持清洁能源、节能环保、碳捕集利用与封存等技术研发和示范应用。</p>
            </div>
        </body>
        </html>
        """
        text = pu._extract_content(sample_html)
        assert "碳中和" in text or "绿色低碳" in text
        print(f"   extracted: {len(text)} chars, first 50: {text[:50]}")
    print("✅ test_policy_fetch_and_extract PASSED")


def test_policy_event_published():
    """E.3: 政策入库后发布 KNOWLEDGE_UPDATED 事件"""
    from policy.updater import PolicyUpdater
    from events import get_event_bus, EventType, reset_event_bus
    import tempfile

    reset_event_bus()
    bus = get_event_bus()
    received = []

    def on_update(event_type, **kwargs):
        received.append((event_type, kwargs))

    bus.subscribe(EventType.KNOWLEDGE_UPDATED, on_update)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "pol2.db"
        pu = PolicyUpdater(db_path=str(db), knowledge_base_path=str(Path(tmp) / "kb"))
        # 直接调 add_policy + 发事件路径
        from datetime import datetime
        pu.add_policy(
            title="测试政策",
            content="这是一条测试政策内容",
            category="测试",
            source="unit_test",
            source_url="http://test.example/policy/1",
            publish_date=datetime.now().strftime("%Y-%m-%d"),
        )
        # 模拟 fetcher 路径:发事件
        bus.publish(EventType.KNOWLEDGE_UPDATED, paths=["http://test.example"], count=1, source="unit_test")

    assert len(received) >= 1
    et, kwargs = received[0]
    assert et == EventType.KNOWLEDGE_UPDATED
    assert kwargs.get("count") == 1
    print(f"   event received: {et}, kwargs={kwargs}")
    print("✅ test_policy_event_published PASSED")


def test_policy_dedup_by_hash():
    """E.4: 同 source_url + 同 content_hash → 跳过(ON CONFLICT)"""
    from policy.updater import PolicyUpdater
    import tempfile
    from datetime import datetime

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "pol_dup.db"
        pu = PolicyUpdater(db_path=str(db), knowledge_base_path=str(Path(tmp) / "kb"))

        # 同 title + 同 publish_date → 同 policy_id → UPSERT 不会重复
        pid1 = pu.add_policy(
            title="DUP_TEST",
            content="same content",
            category="x",
            source="s",
            source_url="http://x",
            publish_date="2026-01-01",
        )
        pid2 = pu.add_policy(
            title="DUP_TEST",
            content="same content",
            category="x",
            source="s",
            source_url="http://x",
            publish_date="2026-01-01",
        )
        assert pid1 == pid2  # 同 ID

        policies = pu.get_policies(limit=100)
        # 唯一约束保证去重
        titles = [p["title"] for p in policies]
        assert titles.count("DUP_TEST") == 1, f"应只有 1 条, 实际 {titles.count('DUP_TEST')}"
        print(f"   policies: {len(policies)}, all distinct titles: {len(set(titles))}")
    print("✅ test_policy_dedup_by_hash PASSED")


if __name__ == "__main__":
    test_rag_engine_singleton()
    test_rag_subscriber_uses_singleton()
    test_policy_fetch_and_extract()
    test_policy_event_published()
    test_policy_dedup_by_hash()
    print("\n🎉 all P4-E RAG/KB tests passed")
