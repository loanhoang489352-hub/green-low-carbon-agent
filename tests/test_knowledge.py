"""
知识库模块测试
"""

import pytest
from knowledge.manager import KnowledgeManager


class TestKnowledgeManager:
    """知识管理器测试"""

    @pytest.fixture
    def kb_path(tmp_path):
        """创建临时知识库"""
        kb = tmp_path / "knowledge_base"
        kb.mkdir()
        # 创建测试文档
        (kb / "test.md").write_text("""# 测试文档
这是测试内容。
碳排放是指...
""", encoding="utf-8")
        return str(kb)

    def test_load_documents(self, kb_path):
        """加载文档"""
        manager = KnowledgeManager(kb_path)
        docs = manager.get_all_documents()
        assert len(docs) > 0

    def test_search(self, kb_path):
        """搜索"""
        manager = KnowledgeManager(kb_path)
        results = manager.search("碳排放")
        assert isinstance(results, list)

    def test_get_document_by_category(self, kb_path):
        """按分类获取"""
        manager = KnowledgeManager(kb_path)
        docs = manager.get_documents_by_category("basic")
        assert isinstance(docs, list)
