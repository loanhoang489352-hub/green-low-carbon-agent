"""
向量数据库 - 存储和检索向量
支持 ChromaDB 和 FAISS
"""

import sys
# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
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
import numpy as np
import json
from dataclasses import dataclass, asdict

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("rag.vector_store")
except Exception:
    import logging
    _logger = logging.getLogger("rag.vector_store")


@dataclass
class Document:
    """文档结构"""
    id: str
    content: str
    metadata: Dict[str, Any]
    embedding: Optional[np.ndarray] = None

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'content': self.content,
            'metadata': self.metadata
        }


class VectorStore:
    """向量数据库基类"""

    def add(self, documents: List[Document]) -> None:
        """添加文档"""
        raise NotImplementedError

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        filter_metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """搜索最相似的文档"""
        raise NotImplementedError

    def delete(self, document_ids: List[str]) -> None:
        """删除文档"""
        raise NotImplementedError

    def count(self) -> int:
        """返回文档数量"""
        raise NotImplementedError

    def clear(self) -> None:
        """清空所有文档"""
        raise NotImplementedError


class ChromaStore(VectorStore):
    """ChromaDB 向量存储"""

    def __init__(
        self,
        persist_directory: str = "./data/chroma_db",
        collection_name: str = "knowledge_base"
    ):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self._client = None
        self._collection = None
        # P5-H.A: 显式记录是否真的用上 PersistentClient(chromadb 1.5 客户端
        # 类名是 Client,无法从 type 区分,需自维护标志)
        self._is_persistent: bool = False
        self._use_inmemory: bool = False
        self._init_collection()

    def _init_collection(self):
        """初始化 ChromaDB 集合

        P5-H.A: Windows 也使用 PersistentClient(chromadb>=0.4.24 Windows 兼容),
        重启不丢索引。安装失败/无 chromadb 时降级为内存存储。
        """
        try:
            import chromadb
            from chromadb.config import Settings

            # P5-H.A: 统一使用 PersistentClient,Windows 也持久化
            # allow_reset=False 防止误调 reset() 清空全部
            Path(self.persist_directory).mkdir(parents=True, exist_ok=True)
            try:
                self._client = chromadb.PersistentClient(
                    path=self.persist_directory,
                    settings=Settings(
                        anonymized_telemetry=False,
                        allow_reset=False,
                    ),
                )
                self._is_persistent = True
            except Exception as e:
                # Windows 上偶发的 sqlite/native lib 兼容问题,降级为 EphemeralClient
                _logger.warning(
                    "PersistentClient 初始化失败,降级 EphemeralClient(重启会丢): %s", e,
                )
                self._client = chromadb.EphemeralClient(
                    settings=Settings(anonymized_telemetry=False)
                )
                self._is_persistent = False

            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                metadata={"description": "知识库向量存储"}
            )
            print(f"[OK] ChromaDB 集合 '{self.collection_name}' 初始化完成 (path={self.persist_directory}, persistent={self._is_persistent})")

        except ImportError:
            _logger.warning("ChromaDB 未安装,使用内存存储")
            self._client = None
            self._use_inmemory = True
            self._is_persistent = False
            self._inmemory_docs: Dict[str, Document] = {}
            self._inmemory_embeddings: List[np.ndarray] = []

    @property
    def is_persistent(self) -> bool:
        """P5-H.A: 是否真的使用 PersistentClient(非 EphemeralClient / 内存降级)"""
        return self._is_persistent

    def add(self, documents: List[Document]) -> None:
        """添加文档到 ChromaDB"""
        if self._client is None:
            self._add_inmemory(documents)
            return

        ids = [doc.id for doc in documents]
        contents = [doc.content for doc in documents]
        metadatas = [doc.metadata for doc in documents]
        embeddings = [doc.embedding.tolist() for doc in documents if doc.embedding is not None]

        # ChromaDB 要求所有文档都有 embedding
        if embeddings:
            self._collection.add(
                ids=ids,
                documents=contents,
                metadatas=metadatas,
                embeddings=embeddings
            )

    def _add_inmemory(self, documents: List[Document]) -> None:
        """内存存储（降级方案）"""
        for doc in documents:
            self._inmemory_docs[doc.id] = doc
            if doc.embedding is not None:
                self._inmemory_embeddings.append(doc.embedding)

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        filter_metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """搜索"""
        if self._client is None:
            return self._search_inmemory(query_embedding, top_k)

        where_clause = filter_metadata if filter_metadata else None

        # 确保embedding是2D数组
        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)
        elif query_embedding.ndim == 3:
            query_embedding = query_embedding.reshape(query_embedding.shape[0], -1)

        # 展平为2D: (1, dim) 或 (n, dim)
        if query_embedding.ndim > 2:
            query_embedding = query_embedding.reshape(-1, query_embedding.shape[-1])

        results = self._collection.query(
            query_embeddings=query_embedding.tolist(),
            n_results=top_k,
            where=where_clause,
            include=["documents", "metadatas", "distances"]
        )

        search_results = []
        if results['documents'] and results['documents'][0]:
            for i, doc_id in enumerate(results['ids'][0]):
                d = results['distances'][0][i]
                # ChromaDB 默认是 squared L2, 取倒数归一化到 (0, 1]
                # 1/(1+d) 始终为正,d=0 时为 1,d→∞ 时为 0
                search_results.append({
                    'id': doc_id,
                    'content': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': d,
                    'score': float(1.0 / (1.0 + d)),  # 兼容非归一化向量
                })

        return search_results

    def _search_inmemory(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """内存搜索（降级方案）- 使用余弦相似度"""
        if not self._inmemory_embeddings:
            return []

        # 计算相似度
        similarities = []
        for i, emb in enumerate(self._inmemory_embeddings):
            sim = np.dot(query_embedding, emb) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(emb)
            )
            similarities.append((i, float(sim)))

        # 排序并返回 top_k
        similarities.sort(key=lambda x: x[1], reverse=True)
        results = []
        for i, sim in similarities[:top_k]:
            doc = list(self._inmemory_docs.values())[i]
            results.append({
                'id': doc.id,
                'content': doc.content,
                'metadata': doc.metadata,
                'distance': 1.0 - sim,
                'score': sim
            })

        return results

    def delete(self, document_ids: List[str]) -> None:
        """删除文档"""
        if self._client is None:
            for doc_id in document_ids:
                self._inmemory_docs.pop(doc_id, None)
            return

        self._collection.delete(ids=document_ids)

    def count(self) -> int:
        """返回文档数量"""
        if self._client is None:
            return len(self._inmemory_docs)
        return self._collection.count()

    def clear(self) -> None:
        """清空"""
        if self._client is None:
            self._inmemory_docs.clear()
            self._inmemory_embeddings.clear()
            return

        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name
        )


class FAISSStore(VectorStore):
    """FAISS 向量存储"""

    def __init__(
        self,
        index_path: str = "./data/faiss.index",
        docs_path: str = "./data/faiss_docs.json"
    ):
        self.index_path = index_path
        self.docs_path = docs_path
        self._index = None
        self._documents: Dict[str, Document] = {}
        self._id_map: Dict[int, str] = {}  # FAISS索引 -> 文档ID
        self._next_idx = 0
        self._load()

    def _load(self):
        """加载索引"""
        try:
            import faiss
            import pickle

            if Path(self.index_path).exists():
                self._index = faiss.read_index(self.index_path)
                with open(self.docs_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._documents = {d['id']: Document(**d) for d in data}
                    self._next_idx = len(self._documents)
                print(f"[OK] FAISS 索引加载完成 ({self._index.ntotal} 条记录)")
            else:
                self._dimension = 384  # 默认维度
                self._index = None
                print("📝 FAISS 将使用新的空索引")

        except ImportError:
            _logger.warning("faiss 或 pickle 不可用")
            self._index = None

    def add(self, documents: List[Document]) -> None:
        """添加文档"""
        if self._index is None:
            return

        import faiss
        import numpy as np

        embeddings = np.array([doc.embedding for doc in documents]).astype('float32')
        doc_ids = [doc.id for doc in documents]

        # 添加到索引
        if embeddings.shape[0] > 0:
            self._index.add(embeddings)

            for i, doc_id in enumerate(doc_ids):
                self._id_map[self._next_idx + i] = doc_id

            self._next_idx += len(documents)

            for doc in documents:
                self._documents[doc.id] = doc

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        filter_metadata: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        """搜索"""
        if self._index is None or self._index.ntotal == 0:
            return []

        import faiss
        import numpy as np

        query = np.array([query_embedding]).astype('float32')
        distances, indices = self._index.search(query, top_k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0:
                continue
            doc_id = self._id_map.get(int(idx))
            if doc_id and doc_id in self._documents:
                doc = self._documents[doc_id]
                if filter_metadata:
                    if not all(doc.metadata.get(k) == v for k, v in filter_metadata.items()):
                        continue
                results.append({
                    'id': doc.id,
                    'content': doc.content,
                    'metadata': doc.metadata,
                    'distance': float(distances[0][i]),
                    'score': float(1.0 / (1.0 + distances[0][i]))
                })

        return results

    def save(self):
        """保存索引"""
        if self._index is None:
            return

        import faiss
        faiss.write_index(self._index, self.index_path)

        with open(self.docs_path, 'w', encoding='utf-8') as f:
            json.dump([asdict(d) for d in self._documents.values()], f, ensure_ascii=False, default=str)

    def delete(self, document_ids: List[str]) -> None:
        """删除（FAISS不支持高效删除，建议重建索引）"""
        for doc_id in document_ids:
            self._documents.pop(doc_id, None)

    def count(self) -> int:
        return len(self._documents)

    def clear(self) -> None:
        self._documents.clear()
        self._id_map.clear()
        self._next_idx = 0
        if self._index is not None:
            import faiss
            dim = int(self._index.d)
            self._index = faiss.IndexFlatL2(dim)


def create_vector_store(
    store_type: str = "chroma",
    persist_directory: str = "./data/chroma_db",
    collection_name: str = "knowledge_base"
) -> VectorStore:
    """工厂函数：创建向量存储"""
    if store_type == "faiss":
        return FAISSStore()
    else:
        return ChromaStore(persist_directory=persist_directory, collection_name=collection_name)
