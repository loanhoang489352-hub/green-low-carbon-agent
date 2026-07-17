"""
知识库基类
定义知识库接口和数据结构
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class KnowledgeDocument:
    """知识文档"""

    def __init__(
        self,
        id: str,
        title: str,
        content: str,
        category: str,
        tags: List[str],
        source: str,
        created_at: str,
        updated_at: str,
        version: int = 1,
        embedding: Optional[List[float]] = None,
    ):
        self.id = id
        self.title = title
        self.content = content
        self.category = category
        self.tags = tags
        self.source = source
        self.created_at = created_at
        self.updated_at = updated_at
        self.version = version
        self.embedding = embedding


class KnowledgeSearchResult:
    """知识检索结果"""

    def __init__(self, document: KnowledgeDocument, score: float, highlight: str):
        self.document = document
        self.score = score
        self.highlight = highlight


class BaseKnowledgeBase(ABC):
    """知识库抽象基类"""

    @abstractmethod
    def add_document(self, doc: KnowledgeDocument) -> bool:
        """添加文档"""
        pass

    @abstractmethod
    def search(self, query: str, top_k: int = 5):
        """搜索文档"""
        pass

    @abstractmethod
    def get_document(self, doc_id: str) -> Optional[KnowledgeDocument]:
        """获取文档"""
        pass

    @abstractmethod
    def update_document(self, doc: KnowledgeDocument) -> bool:
        """更新文档"""
        pass

    @abstractmethod
    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        pass

    @abstractmethod
    def get_all_documents(self) -> List[KnowledgeDocument]:
        """获取所有文档"""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        pass
