"""
知识库管理器(P5-H.B: 标记为 deprecated,新代码请用 RAGEngine)

历史:
- P0~P3 用关键词 TF-IDF 检索,RAGEngine 出现后职责重叠
- P5-H.B: search() 发 DeprecationWarning,建议改用
    from rag.rag_engine import get_rag_engine; engine.retrieve(query, top_k=N)

仍保留:
- _load_knowledge_base / get_categories / get_stats 等本地文件操作型 API
- 单纯关键词搜索(适合无 embedder 的场景);RAGEngine 不可用时仍可降级
"""

# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
import sys

if sys.platform == "win32":
    import io

    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import uuid
import warnings
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import hashlib

# P5-F: 模块级 logger
try:
    from observability import get_logger

    _logger = get_logger("knowledge.manager")
except Exception:
    import logging

    _logger = logging.getLogger("knowledge.manager")

# 添加项目根目录
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 延迟导入base模块
_base_module = None


def _get_base():
    global _base_module
    if _base_module is None:
        from knowledge.base import KnowledgeDocument, KnowledgeSearchResult, BaseKnowledgeBase

        _base_module = (KnowledgeDocument, KnowledgeSearchResult, BaseKnowledgeBase)
    return _base_module


class KnowledgeManager:
    """知识库管理器"""

    def __init__(self, base_path: str = None):
        """
        初始化知识库管理器
        """
        if base_path is None:
            base_path = str(project_root / "knowledge_base")

        self.base_path = Path(base_path)
        self.documents: Dict[str, "KnowledgeDocument"] = {}
        self.documents_by_category: Dict[str, List[str]] = {}

        # 加载知识库
        self._load_knowledge_base()

        print(f"[Knowledge] Documents loaded: {len(self.documents)}")

    def _load_knowledge_base(self):
        """加载知识库"""
        if not self.base_path.exists():
            print(f"   警告: 知识库目录不存在: {self.base_path}")
            return

        # 遍历所有子目录和Markdown文件
        for category_dir in self.base_path.iterdir():
            if category_dir.is_dir():
                category = category_dir.name
                self.documents_by_category[category] = []

                for md_file in category_dir.glob("*.md"):
                    doc = self._parse_markdown_file(md_file, category)
                    if doc:
                        self.documents[doc.id] = doc
                        self.documents_by_category[category].append(doc.id)

    def _parse_markdown_file(self, file_path: Path, category: str) -> Optional["KnowledgeDocument"]:
        """解析Markdown文件"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 提取标题
            title = file_path.stem
            lines = content.split("\n")
            for line in lines:
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

            # 提取标签
            tags = self._extract_tags(content)

            # 生成文档ID
            doc_id = hashlib.md5(f"{category}:{title}".encode()).hexdigest()[:12]

            KnowledgeDocument = _get_base()[0]

            return KnowledgeDocument(
                id=doc_id,
                title=title,
                content=content,
                category=category,
                tags=tags,
                source=str(file_path),
                created_at=self._get_file_time(file_path),
                updated_at=self._get_file_time(file_path),
                version=1,
            )

        except Exception as e:
            print(f"   解析文件失败: {file_path}, 错误: {e}")
            return None

    def _extract_tags(self, content: str) -> List[str]:
        """从内容中提取标签"""
        tag_keywords = {
            "碳中和": ["碳中和", "碳达峰", "双碳"],
            "出行": ["出行", "交通", "开车", "骑行", "步行"],
            "家居": ["家居", "家电", "空调", "节能", "用电"],
            "饮食": ["饮食", "食物", "素食", "外卖", "肉类"],
            "消费": ["消费", "购物", "包装", "一次性"],
            "政策": ["政策", "补贴", "碳市场", "碳积分"],
        }

        tags = []
        for tag, keywords in tag_keywords.items():
            if any(kw in content for kw in keywords):
                tags.append(tag)

        return tags if tags else ["一般"]

    def _get_file_time(self, file_path: Path) -> str:
        """获取文件时间"""
        try:
            timestamp = file_path.stat().st_mtime
            return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        except:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add_document(self, doc: "KnowledgeDocument") -> bool:
        """添加文档"""
        try:
            doc.id = doc.id or str(uuid.uuid4())
            doc.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            doc.updated_at = doc.created_at

            self.documents[doc.id] = doc

            if doc.category not in self.documents_by_category:
                self.documents_by_category[doc.category] = []
            self.documents_by_category[doc.category].append(doc.id)

            return True
        except Exception as e:
            print(f"添加文档失败: {e}")
            return False

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """搜索文档

        P5-H.B: 优先委托给 RAGEngine.retrieve(),失败/不可用时降级为关键词搜索。
        发 DeprecationWarning 提示调用方迁移。
        """
        # 优先 RAGEngine
        try:
            from rag.rag_engine import get_rag_engine

            engine = get_rag_engine()
            if engine is not None and getattr(engine, "_initialized", False):
                rag_results = engine.retrieve(query, top_k=top_k)
                if rag_results:
                    # 转换 RAGEngine 的 RetrievalResult → KnowledgeManager 兼容格式
                    converted = []
                    for r in rag_results:
                        md = getattr(r, "metadata", {}) or {}
                        converted.append(
                            {
                                "id": getattr(r, "id", ""),
                                "title": md.get("source", "")
                                .replace("\\", "/")
                                .split("/")[-1]
                                .replace(".md", "")
                                or "knowledge",
                                "content": getattr(r, "content", ""),
                                "category": md.get("category", "rag"),
                                "tags": [],
                                "score": float(getattr(r, "score", 0.0)),
                                "highlight": getattr(r, "content", "")[:200],
                            }
                        )
                    return converted
        except Exception as e:
            _logger.debug("[KnowledgeManager] RAGEngine 不可用,降级关键词: %s", e)

        # 降级:旧关键词路径
        warnings.warn(
            "KnowledgeManager.search() 关键词降级路径已废弃,新代码请用 "
            "rag.rag_engine.get_rag_engine().retrieve()",
            DeprecationWarning,
            stacklevel=2,
        )
        query_keywords = self._extract_keywords(query)

        scored_docs = []
        for doc_id, doc in self.documents.items():
            score = self._calculate_relevance(doc, query_keywords)
            if score > 0:
                scored_docs.append((doc, score))

        scored_docs.sort(key=lambda x: x[1], reverse=True)

        results = []
        for doc, score in scored_docs[:top_k]:
            highlight = self._get_highlight(doc.content, query_keywords)
            results.append(
                {
                    "id": doc.id,
                    "title": doc.title,
                    "content": doc.content,
                    "category": doc.category,
                    "tags": doc.tags,
                    "score": score,
                    "highlight": highlight,
                }
            )

        return results

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        chinese_keywords = [
            "碳中和",
            "碳达峰",
            "碳足迹",
            "碳排放",
            "低碳",
            "环保",
            "绿色",
            "节能",
            "减排",
            "可持续",
            "太阳能",
            "风能",
            "电动车",
            "新能源",
            "空调",
            "冰箱",
            "洗衣机",
            "LED",
            "能效",
            "出行",
            "交通",
            "开车",
            "骑行",
            "步行",
            "公交",
            "地铁",
            "素食",
            "肉类",
            "一次性",
            "塑料",
            "垃圾分类",
            "政策",
            "补贴",
            "碳积分",
            "家居",
            "用电",
            "用水",
            "购物",
            "消费",
            "包装",
        ]

        found = []
        for kw in chinese_keywords:
            if kw in text:
                found.append(kw)

        return found if found else [text[:10]]

    def _calculate_relevance(self, doc: "KnowledgeDocument", keywords: List[str]) -> float:
        """计算文档与查询的相关性"""
        if not keywords:
            return 0

        content_lower = doc.content.lower()
        title_lower = doc.title.lower()

        score = 0

        for kw in keywords:
            if kw in title_lower:
                score += 3.0
            if kw in content_lower:
                score += 1.0

        for kw in keywords:
            if kw in doc.tags:
                score += 2.0

        max_possible = len(keywords) * 6
        return min(score / max_possible, 1.0) if max_possible > 0 else 0

    def _get_highlight(self, content: str, keywords: List[str], context_len: int = 100) -> str:
        """获取高亮片段"""
        content_lower = content.lower()

        best_pos = -1
        for kw in keywords:
            pos = content_lower.find(kw.lower())
            if pos != -1:
                if best_pos == -1 or pos < best_pos:
                    best_pos = pos

        if best_pos == -1:
            return content[:200] + "..." if len(content) > 200 else content

        start = max(0, best_pos - context_len // 2)
        end = min(len(content), best_pos + context_len)

        highlight = content[start:end]

        if start > 0:
            highlight = "..." + highlight
        if end < len(content):
            highlight = highlight + "..."

        return highlight

    def get_document(self, doc_id: str) -> Optional["KnowledgeDocument"]:
        """获取文档"""
        return self.documents.get(doc_id)

    def update_document(self, doc: "KnowledgeDocument") -> bool:
        """更新文档"""
        if doc.id not in self.documents:
            return False

        doc.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        doc.version += 1
        self.documents[doc.id] = doc
        return True

    def delete_document(self, doc_id: str) -> bool:
        """删除文档"""
        if doc_id not in self.documents:
            return False

        doc = self.documents[doc_id]

        if doc.category in self.documents_by_category:
            self.documents_by_category[doc.category].remove(doc_id)

        del self.documents[doc_id]
        return True

    def get_all_documents(self) -> List["KnowledgeDocument"]:
        """获取所有文档"""
        return list(self.documents.values())

    def get_documents_by_category(self, category: str) -> List["KnowledgeDocument"]:
        """获取指定分类的文档"""
        doc_ids = self.documents_by_category.get(category, [])
        return [self.documents[doc_id] for doc_id in doc_ids if doc_id in self.documents]

    def get_categories(self) -> List[str]:
        """获取所有分类"""
        return list(self.documents_by_category.keys())

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "total_documents": len(self.documents),
            "categories": {
                cat: len(doc_ids) for cat, doc_ids in self.documents_by_category.items()
            },
            "recent_updated": self._get_recent_updated_docs(5),
        }

    def _get_recent_updated_docs(self, limit: int) -> List[Dict]:
        """获取最近更新的文档"""
        docs = sorted(self.documents.values(), key=lambda d: d.updated_at, reverse=True)[:limit]

        return [
            {"title": d.title, "category": d.category, "updated_at": d.updated_at} for d in docs
        ]

    def reload(self):
        """重新加载知识库"""
        self.documents.clear()
        self.documents_by_category.clear()
        self._load_knowledge_base()
