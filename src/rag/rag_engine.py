"""
RAG 引擎 - 检索增强生成的核心引擎
整合嵌入、存储、检索和生成
"""

# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
import sys
if sys.platform == 'win32':
    import io
    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import json
import uuid
import time
import threading

from .embedder import Embedder, create_embedder, SentenceTransformerEmbedder
from .vector_store import VectorStore, Document, create_vector_store
from .retriever import Retriever, SemanticRetriever, BM25Retriever, HybridRetriever, RetrievalResult

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("rag.engine")
except Exception:
    import logging
    _logger = logging.getLogger("rag.engine")


@dataclass
class RAGConfig:
    """RAG 配置"""
    enabled: bool = True
    provider: str = "sentence-transformers"  # sentence-transformers, openai
    embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2"
    vector_store_type: str = "chroma"  # chroma, faiss, inmemory
    persist_directory: str = "./data/vector_db"
    collection_name: str = "knowledge_base"
    default_top_k: int = 5
    # P6.S.9: 预过滤。HybridRetriever 综合分 = semantic*0.6 + bm25*0.4,
    # 真实相关文档常在 0.01-0.04 区间(MiniLM + ChromaDB 1/(1+d²)),
    # 0.05 预过滤基本不挡召回,主要靠 post_filter + 相对阈值
    min_similarity: float = 0.05
    hybrid_search: bool = True  # 是否启用混合搜索
    semantic_weight: float = 0.6  # 语义权重
    # P6.S.9: 后置兜底 — 绝对下界(很低的最小值,主要靠相对阈值过滤)
    # 真实召回分常在 0.01-0.04,设 0.005 仅挡掉完全不相关;
    # 真要过滤"0.04 噪声"靠 max_score * 0.3 相对阈值
    post_filter_threshold: float = 0.005
    # P6.S.9: 初始候选倍数 (top_k=5 → 5*4=20 候选 → rerank → top_k=5)
    initial_fetch_multiplier: int = 4
    # P6.S.9: 相对下界 — 仅保留 max_score * 此比例 以上的文档
    relative_threshold_ratio: float = 0.3


class RAGEngine:
    """
    RAG 引擎
    提供完整的检索增强生成能力
    """

    def __init__(self, config: RAGConfig = None):
        self.config = config or RAGConfig()
        self._embedder: Optional[Embedder] = None
        self._vector_store: Optional[VectorStore] = None
        self._retriever: Optional[Retriever] = None
        self._bm25_documents: List[Dict] = []
        self._initialized = False

        # 索引统计
        self.stats = {
            'total_documents': 0,
            'last_index_time': None,
            'total_queries': 0,
            'avg_query_time_ms': 0
        }

        # P5-H.C: 异步重建状态
        self._rebuild_state: Dict[str, Any] = {
            "state": "idle",  # idle | running | done | error
            "progress": 0,
            "total": 0,
            "message": "",
        }
        self._rebuild_lock = threading.Lock()

    @property
    def is_enabled(self) -> bool:
        return self.config.enabled and self._initialized

    def initialize(self, knowledge_base_path: str = None) -> bool:
        """
        初始化 RAG 引擎

        Args:
            knowledge_base_path: 知识库路径

        Returns:
            是否初始化成功
        """
        if not self.config.enabled:
            _logger.warning("RAG 功能已禁用")
            return False

        try:
            print("🔧 初始化 RAG 引擎...")

            # 1. 初始化嵌入器
            print("   - 初始化嵌入器...")
            self._embedder = create_embedder(
                provider=self.config.provider,
                model_name=self.config.embedding_model
            )
            _ = self._embedder.dimension  # 触发模型加载

            # 2. 初始化向量存储
            print("   - 初始化向量存储...")
            self._vector_store = create_vector_store(
                store_type=self.config.vector_store_type,
                persist_directory=self.config.persist_directory,
                collection_name=self.config.collection_name
            )

            # 3. 初始化检索器
            print("   - 初始化检索器...")
            if self.config.hybrid_search:
                self._retriever = HybridRetriever(
                    vector_store=self._vector_store,
                    embedder=self._embedder,
                    bm25_documents=self._bm25_documents,
                    semantic_weight=self.config.semantic_weight
                )
            else:
                self._retriever = SemanticRetriever(
                    vector_store=self._vector_store,
                    embedder=self._embedder,
                    default_top_k=self.config.default_top_k
                )

            # 4. 加载知识库
            if knowledge_base_path:
                self.load_knowledge_base(knowledge_base_path)

            self._initialized = True
            print("[OK] RAG 引擎初始化完成")
            return True

        except Exception as e:
            print(f"[ERR] RAG 引擎初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load_knowledge_base(
        self,
        base_path: str,
        categories: List[str] = None,
        force_reload: bool = False
    ) -> int:
        """
        加载知识库文档

        Args:
            base_path: 知识库根目录
            categories: 要加载的分类（如 ["basic", "policy", "guide"]）
            force_reload: 是否强制重新加载

        Returns:
            加载的文档数量
        """
        base_path = Path(base_path)
        if not base_path.exists():
            _logger.warning(f"知识库路径不存在: {base_path}")
            return 0

        # 检查是否已有索引
        existing_count = self._vector_store.count()
        if existing_count > 0 and not force_reload:
            print(f"[KB] 知识库已有 {existing_count} 条索引，跳过加载")
            return existing_count

        print(f"[KB] 开始加载知识库: {base_path}")
        documents = []

        # 扫描所有 markdown 文件
        for md_file in base_path.rglob("*.md"):
            # 检查分类
            if categories:
                relative = md_file.relative_to(base_path)
                if len(relative.parts) > 1 and relative.parts[0] not in categories:
                    continue

            # 读取文档
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 解析 YAML front matter（如果有）
                metadata = self._parse_metadata(content)
                metadata['source'] = str(md_file.relative_to(base_path))
                metadata['category'] = md_file.parent.name if len(md_file.parts) > 1 else 'root'

                # 分块
                chunks = self._chunk_document(content, metadata)

                # 生成嵌入并添加
                for chunk in chunks:
                    doc = Document(
                        id=chunk['id'],
                        content=chunk['content'],
                        metadata=chunk['metadata'],
                        embedding=None  # 稍后批量生成
                    )
                    documents.append(doc)

                    # BM25 用分块后的内容
                    self._bm25_documents.append({
                        'id': chunk['id'],
                        'content': chunk['content'],
                        'metadata': chunk['metadata']
                    })

            except Exception as e:
                print(f"   [WARN]  读取失败 {md_file}: {e}")

        if not documents:
            print("   [WARN]  没有找到文档")
            return 0

        print(f"   📄 解析了 {len(documents)} 个文档块")

        # 批量生成嵌入
        print("   🔢 生成向量嵌入...")
        contents = [doc.content for doc in documents]
        embeddings = self._embedder.encode(contents)

        for i, doc in enumerate(documents):
            doc.embedding = embeddings[i]

        # 添加到向量存储
        print("   💾 存储到向量数据库...")
        self._vector_store.add(documents)

        # 更新 BM25 检索器
        if self._retriever and isinstance(self._retriever, HybridRetriever):
            self._retriever.update_bm25_documents(self._bm25_documents)

        # 更新统计
        self.stats['total_documents'] = self._vector_store.count()
        self.stats['last_index_time'] = time.strftime("%Y-%m-%d %H:%M:%S")

        print(f"   [OK] 知识库加载完成 ({self.stats['total_documents']} 个文档)")

        return self.stats['total_documents']

    def _parse_metadata(self, content: str) -> Dict[str, Any]:
        """解析 YAML front matter"""
        metadata = {}

        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                yaml_content = parts[1]
                for line in yaml_content.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        metadata[key.strip()] = value.strip()

        return metadata

    def _chunk_document(
        self,
        content: str,
        metadata: Dict[str, Any],
        chunk_size: int = 500,
        overlap: int = 50
    ) -> List[Dict]:
        """将文档分块"""
        chunks = []

        # 移除 front matter
        if content.startswith('---'):
            content = content.split('---', 2)[-1]

        # 清理
        content = content.strip()

        # 按段落分割
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]

        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) <= chunk_size:
                current_chunk += para + "\n\n"
            else:
                if current_chunk:
                    chunks.append({
                        'id': str(uuid.uuid4()),
                        'content': current_chunk.strip(),
                        'metadata': metadata.copy()
                    })

                # 保持重叠
                if overlap > 0 and len(para) > overlap:
                    current_chunk = para[-overlap:] + "\n\n" + para
                else:
                    current_chunk = para + "\n\n"

        # 最后一个块
        if current_chunk.strip():
            chunks.append({
                'id': str(uuid.uuid4()),
                'content': current_chunk.strip(),
                'metadata': metadata.copy()
            })

        return chunks

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        filter_metadata: Dict[str, Any] = None
    ) -> List[RetrievalResult]:
        """
        检索相关文档

        P6.S.9: 二段式召回
        1. 初始: 取 top_k * multiplier 候选(默认 20) → 保留高分候选
        2. 后置: 严格 score >= post_filter_threshold(默认 0.5)兜底
        3. rerank: 若 retriever 配了 reranker,精排
        4. 截断: 返回 top_k

        Args:
            query: 查询文本
            top_k: 返回数量
            filter_metadata: 元数据过滤

        Returns:
            检索结果列表
        """
        if not self.is_enabled:
            return []

        start_time = time.time()
        top_k = top_k or self.config.default_top_k
        initial_top_k = top_k * self.config.initial_fetch_multiplier

        # 第一阶段: 初筛(放宽,召回率高)
        results = self._retriever.retrieve(
            query=query,
            top_k=initial_top_k,
            filter_metadata=filter_metadata,
            min_score=self.config.min_similarity,
        )

        # 第二阶段: rerank 精排(若 retriever 配了 reranker)
        if results and getattr(self._retriever, "reranker", None):
            try:
                results = self._retriever.reranker.rerank(query, results)
            except Exception:
                # rerank 失败回退到原序
                pass

        # 第三阶段: 后置兜底过滤
        # P6.S.9: 用绝对下界 + 相对下界组合(适应不同评分尺度)
        #   - 绝对下界 (post_filter_threshold): 0.005,仅挡完全不相关
        #   - 相对下界: max_score * 0.3,砍掉与最相关文档差距太大的
        # 注: MiniLM + ChromaDB 1/(1+d²) 真实召回分常在 0.01-0.04,
        #     单纯 0.5/0.1 绝对阈值会砍光真实召回,所以两者取大
        abs_threshold = self.config.post_filter_threshold
        before_count = len(results)
        if results:
            max_score = max(r.score for r in results)
            # 关键:abs_threshold 应是绝对下界(很低的最小值),不是主要过滤
            # max(0.005, max*0.3) → 真实召回 max=0.02 → 阈值 0.006 → 5 个全过
            rel_threshold = max(abs_threshold, max_score * 0.3)
        else:
            rel_threshold = abs_threshold
        results = [r for r in results if r.score >= rel_threshold]
        dropped = before_count - len(results)
        if dropped:
            import logging
            logging.getLogger(__name__).debug(
                "[RAG] post_filter dropped=%d/%d (abs=%.4f rel=%.4f query='%s')",
                dropped, before_count, abs_threshold, rel_threshold, query[:50],
            )

        # 第四阶段: 截断到 top_k
        results = results[:top_k]

        # 更新统计
        self.stats['total_queries'] += 1
        elapsed = (time.time() - start_time) * 1000
        total_time = self.stats['avg_query_time_ms'] * (self.stats['total_queries'] - 1)
        self.stats['avg_query_time_ms'] = (total_time + elapsed) / self.stats['total_queries']

        return results

    def get_context_for_generation(
        self,
        query: str,
        top_k: int = 3,
        include_metadata: bool = True
    ) -> str:
        """
        获取用于生成的上下文

        Args:
            query: 查询
            top_k: 使用的上下文块数量
            include_metadata: 是否包含元数据

        Returns:
            格式化的上下文字符串
        """
        results = self.retrieve(query, top_k=top_k)

        if not results:
            return ""

        context_parts = []
        for i, result in enumerate(results, 1):
            part = f"[来源 {i}]: {result.get_summary()}"
            if include_metadata and result.metadata:
                source = result.metadata.get('source', '')
                category = result.metadata.get('category', '')
                if source:
                    part += f"\n    (来源: {source})"
            context_parts.append(part)

        return "\n\n".join(context_parts)

    def get_retrieval_info(
        self,
        query: str,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """获取检索信息（用于调试和展示）"""
        results = self.retrieve(query, top_k=top_k)

        return {
            'query': query,
            'results': [
                {
                    'id': r.id,
                    'content_preview': r.get_summary(100),
                    'metadata': r.metadata,
                    'score': round(r.score, 4)
                }
                for r in results
            ],
            'total_results': len(results),
            'stats': self.stats
        }

    def add_document(
        self,
        content: str,
        metadata: Dict[str, Any] = None
    ) -> bool:
        """添加单个文档"""
        if not self.is_enabled:
            return False

        try:
            metadata = metadata or {}
            doc_id = str(uuid.uuid4())

            embedding = self._embedder.encode(content)

            doc = Document(
                id=doc_id,
                content=content,
                metadata=metadata,
                embedding=embedding
            )

            self._vector_store.add([doc])

            # BM25
            self._bm25_documents.append({
                'id': doc_id,
                'content': content,
                'metadata': metadata
            })

            if isinstance(self._retriever, HybridRetriever):
                self._retriever.update_bm25_documents(self._bm25_documents)

            self.stats['total_documents'] = self._vector_store.count()
            return True

        except Exception as e:
            print(f"[ERR] 添加文档失败: {e}")
            return False

    def rebuild_index(self, knowledge_base_path: str) -> int:
        """重建索引(同步)"""
        print("🔄 重建知识库索引...")
        self._vector_store.clear()
        self._bm25_documents.clear()
        return self.load_knowledge_base(knowledge_base_path, force_reload=True)

    # ------------------------------------------------------------------
    # P5-H.C: 异步重建 + 进度查询
    # ------------------------------------------------------------------
    def rebuild_index_async(self, knowledge_base_path: str) -> Dict[str, Any]:
        """启动后台重建任务(立刻返回)

        前端可调 GET /api/rag/status 查 {state, progress, total, message}
        若已有任务在跑,返回当前状态而非排队第二次。
        """
        with self._rebuild_lock:
            if self._rebuild_state.get("state") == "running":
                return dict(self._rebuild_state)

            self._rebuild_state = {
                "state": "running",
                "progress": 0,
                "total": 0,
                "message": "starting",
                "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        def _worker():
            try:
                self._update_rebuild_state(message="clearing index", progress=5)
                self._vector_store.clear()
                self._bm25_documents.clear()
                self._update_rebuild_state(message="loading knowledge base", progress=10)
                count = self.load_knowledge_base(knowledge_base_path, force_reload=True)
                self._update_rebuild_state(
                    state="done",
                    progress=100,
                    total=count,
                    message=f"完成,共 {count} 个文档块",
                )
            except Exception as e:
                _logger.exception("[RAG] 异步重建失败: %s", e)
                self._update_rebuild_state(state="error", message=str(e))

        t = threading.Thread(target=_worker, name="rag-rebuild", daemon=True)
        t.start()
        return dict(self._rebuild_state)

    def _update_rebuild_state(self, **kwargs) -> None:
        with self._rebuild_lock:
            self._rebuild_state.update(kwargs)

    def get_rebuild_status(self) -> Dict[str, Any]:
        """P5-H.C: 查异步重建进度"""
        with self._rebuild_lock:
            return dict(self._rebuild_state)

    # ------------------------------------------------------------------
    # P5-H.E: 增量 upsert API
    # ------------------------------------------------------------------
    def add_documents(self, paths: List[str], base_path: Optional[str] = None) -> int:
        """增量加入指定 markdown 文件(不重建全量)

        Args:
            paths: 要加入的 markdown 路径列表(绝对或相对 base_path)
            base_path: 用于计算 metadata.source 的根目录;不传则用 path.parent
        Returns:
            实际加入的文档块数
        """
        if not self.is_enabled:
            return 0

        base = Path(base_path) if base_path else None
        documents: List[Document] = []
        bm25_new: List[Dict] = []

        for p in paths:
            md_file = Path(p)
            if not md_file.exists() or md_file.suffix.lower() != ".md":
                _logger.warning("[RAG] add_documents 跳过(不存在或非 md): %s", md_file)
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
                metadata = self._parse_metadata(content)
                metadata["source"] = (
                    str(md_file.relative_to(base)) if base else str(md_file.name)
                )
                metadata["category"] = (
                    md_file.parent.name if md_file.parent else "root"
                )
                for chunk in self._chunk_document(content, metadata):
                    documents.append(Document(
                        id=chunk["id"],
                        content=chunk["content"],
                        metadata=chunk["metadata"],
                        embedding=None,
                    ))
                    bm25_new.append({
                        "id": chunk["id"],
                        "content": chunk["content"],
                        "metadata": chunk["metadata"],
                    })
            except Exception as e:
                _logger.warning("[RAG] add_documents 读失败 %s: %s", md_file, e)

        if not documents:
            return 0

        contents = [d.content for d in documents]
        embeddings = self._embedder.encode(contents)
        for i, d in enumerate(documents):
            d.embedding = embeddings[i]

        self._vector_store.add(documents)
        self._bm25_documents.extend(bm25_new)

        if isinstance(self._retriever, HybridRetriever):
            self._retriever.update_bm25_documents(self._bm25_documents)

        self.stats["total_documents"] = self._vector_store.count()
        self.stats["last_index_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        return len(documents)

    def delete_documents(self, sources: List[str]) -> int:
        """按 metadata.source(文件名或相对路径)删除该文档的所有 chunk

        Returns:
            实际删除的 chunk 数(粗略估计,删除前后 count 差)
        """
        if not self.is_enabled:
            return 0

        before = self._vector_store.count()

        # 收集所有匹配 source 的 chunk id(BM25 / ChromaDB 都需要)
        norm_sources = {self._norm_source(s) for s in sources}
        ids_to_delete: List[str] = []
        remaining_bm25: List[Dict] = []
        for d in self._bm25_documents:
            doc_src = self._norm_source(d.get("metadata", {}).get("source", ""))
            if doc_src in norm_sources:
                ids_to_delete.append(d["id"])
            else:
                remaining_bm25.append(d)

        if ids_to_delete:
            self._vector_store.delete(ids_to_delete)
        self._bm25_documents = remaining_bm25

        if isinstance(self._retriever, HybridRetriever):
            self._retriever.update_bm25_documents(self._bm25_documents)

        after = self._vector_store.count()
        self.stats["total_documents"] = after
        return max(before - after, len(ids_to_delete))

    @staticmethod
    def _norm_source(s: str) -> str:
        """规范化 source 路径用于比较(统一分隔符 + 取文件名)"""
        if not s:
            return ""
        s = s.replace("\\", "/").strip()
        # 允许传 "xxx.md" 或 "policy/xxx.md" 或 stem "xxx" 三种形式
        # 统一比较 stem
        name = s.split("/")[-1]
        if name.endswith(".md"):
            name = name[:-3]
        return name

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            **self.stats,
            'vector_store_count': self._vector_store.count() if self._vector_store else 0,
            'bm25_doc_count': len(self._bm25_documents),
            'is_enabled': self.is_enabled,
            'config': {
                'provider': self.config.provider,
                'embedding_model': self.config.embedding_model,
                'vector_store_type': self.config.vector_store_type,
                'hybrid_search': self.config.hybrid_search
            }
        }


def create_rag_engine(config: RAGConfig = None) -> RAGEngine:
    """工厂函数：创建 RAG 引擎"""
    return RAGEngine(config)


# P4-E.1: RAGEngine 单例(双检锁),供 RAG 订阅者直接调用
_rag_engine_instance: Optional["RAGEngine"] = None
_rag_engine_lock = threading.Lock()


def get_rag_engine(config: RAGConfig = None) -> RAGEngine:
    """获取 RAG 引擎单例(P4-E.1)

    首次调用时若传 config,则用该 config;之后忽略。
    """
    global _rag_engine_instance
    if _rag_engine_instance is None:
        with _rag_engine_lock:
            if _rag_engine_instance is None:
                _rag_engine_instance = RAGEngine(config or RAGConfig())
    return _rag_engine_instance


def reset_rag_engine() -> None:
    """重置单例(测试用)"""
    global _rag_engine_instance
    with _rag_engine_lock:
        _rag_engine_instance = None
