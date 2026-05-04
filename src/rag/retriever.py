"""
检索器 - 从知识库中检索相关文档
支持多种检索策略
"""

import sys
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
import re


@dataclass
class RetrievalResult:
    """检索结果"""
    id: str
    content: str
    metadata: Dict[str, Any]
    score: float
    query: str

    def get_summary(self, max_length: int = 200) -> str:
        """获取摘要"""
        if len(self.content) <= max_length:
            return self.content

        # 尝试在句号处截断
        truncated = self.content[:max_length]
        last_period = truncated.rfind('。')
        if last_period > max_length * 0.7:
            return truncated[:last_period + 1]
        return truncated + "..."


class Retriever:
    """检索器基类"""

    def __init__(self, vector_store, embedder, reranker=None):
        self.vector_store = vector_store
        self.embedder = embedder
        self.reranker = reranker  # 可选的重新排序器

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Dict[str, Any] = None,
        min_score: float = 0.0
    ) -> List[RetrievalResult]:
        """
        检索相关文档

        Args:
            query: 查询文本
            top_k: 返回数量
            filter_metadata: 元数据过滤条件
            min_score: 最低相似度分数

        Returns:
            检索结果列表
        """
        raise NotImplementedError


class SemanticRetriever(Retriever):
    """语义检索器 - 基于向量相似度"""

    def __init__(
        self,
        vector_store,
        embedder,
        reranker=None,
        default_top_k: int = 5
    ):
        super().__init__(vector_store, embedder, reranker)
        self.default_top_k = default_top_k

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        filter_metadata: Dict[str, Any] = None,
        min_score: float = 0.3
    ) -> List[RetrievalResult]:
        """语义检索"""
        top_k = top_k or self.default_top_k

        # 生成查询向量
        query_embedding = self.embedder.encode(query)

        # 向量搜索
        results = self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k * 2,  # 多取一些用于重排序
            filter_metadata=filter_metadata
        )

        # 过滤和转换结果
        retrieval_results = []
        for r in results:
            if r['score'] >= min_score:
                retrieval_results.append(RetrievalResult(
                    id=r['id'],
                    content=r['content'],
                    metadata=r.get('metadata', {}),
                    score=r['score'],
                    query=query
                ))

        # 重排序（如有）
        if self.reranker and retrieval_results:
            retrieval_results = self._rerank(query, retrieval_results)

        return retrieval_results[:top_k]

    def _rerank(
        self,
        query: str,
        results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """重新排序"""
        # 简单重排序：结合语义相似度和关键词匹配
        query_keywords = set(query.lower().split())

        def rerank_score(result: RetrievalResult) -> float:
            content_lower = result.content.lower()

            # 关键词匹配分数
            keyword_matches = sum(1 for kw in query_keywords if kw in content_lower)
            keyword_score = keyword_matches / max(len(query_keywords), 1)

            # 综合分数
            return result.score * 0.7 + keyword_score * 0.3

        return sorted(results, key=rerank_score, reverse=True)


class BM25Retriever(Retriever):
    """BM25 检索器 - 基于关键词的传统检索"""

    def __init__(self, documents: List[Dict] = None):
        self.documents = documents or []
        self._doc_freq: Dict[str, int] = {}  # 词 -> 包含该词的文档数
        self._avg_doc_len = 0
        self.k1 = 1.5  # BM25 参数
        self.b = 0.75  # BM25 参数

        if self.documents:
            self._build_index()

    def _build_index(self):
        """构建 BM25 索引"""
        import math

        n_docs = len(self.documents)
        all_terms = set()

        # 统计词频
        for doc in self.documents:
            content = doc.get('content', '')
            terms = self._tokenize(content)
            unique_terms = set(terms)
            all_terms.update(unique_terms)

            for term in unique_terms:
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1

        # 计算平均文档长度
        total_len = sum(len(self._tokenize(d.get('content', ''))) for d in self.documents)
        self._avg_doc_len = total_len / max(n_docs, 1)

        # 计算 IDF
        self._idf: Dict[str, float] = {}
        for term, df in self._doc_freq.items():
            self._idf[term] = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)

    def _tokenize(self, text: str) -> List[str]:
        """简单分词"""
        # 中文：按字符 + 简单词汇
        # 英文：按空格
        text = text.lower()
        # 提取英文单词和中文词
        tokens = re.findall(r'[\u4e00-\u9fff]+|[a-z]+', text)
        return tokens

    def _get_term_freq(self, doc_content: str, term: str) -> int:
        """获取词频"""
        tokens = self._tokenize(doc_content)
        return tokens.count(term.lower())

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Dict[str, Any] = None,
        min_score: float = 0.0
    ) -> List[RetrievalResult]:
        """BM25 检索"""
        query_terms = self._tokenize(query)

        scores: Dict[str, float] = {}
        for doc in self.documents:
            doc_id = doc.get('id', '')
            content = doc.get('content', '')
            metadata = doc.get('metadata', {})

            # 元数据过滤
            if filter_metadata:
                if not all(metadata.get(k) == v for k, v in filter_metadata.items()):
                    continue

            doc_len = len(self._tokenize(content))
            score = 0.0

            for term in query_terms:
                if term not in self._idf:
                    continue

                tf = self._get_term_freq(content, term)
                idf = self._idf[term]

                # BM25 公式
                term_score = idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * doc_len / max(self._avg_doc_len, 1))
                )
                score += term_score

            if score > min_score:
                scores[doc_id] = score

        # 排序
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        results = []
        for doc_id in sorted_ids[:top_k]:
            doc = next((d for d in self.documents if d.get('id') == doc_id), None)
            if doc:
                results.append(RetrievalResult(
                    id=doc_id,
                    content=doc['content'],
                    metadata=doc.get('metadata', {}),
                    score=scores[doc_id],
                    query=query
                ))

        return results

    def add_documents(self, documents: List[Dict]):
        """添加文档"""
        self.documents.extend(documents)
        self._build_index()

    def clear(self):
        """清空"""
        self.documents.clear()
        self._doc_freq.clear()
        if hasattr(self, '_idf'):
            self._idf.clear()


class HybridRetriever(Retriever):
    """混合检索器 - 结合语义和关键词"""

    def __init__(
        self,
        vector_store,
        embedder,
        bm25_documents: List[Dict] = None,
        semantic_weight: float = 0.6,
        bm25_weight: float = 0.4
    ):
        self.semantic_retriever = SemanticRetriever(vector_store, embedder)
        self.bm25_retriever = BM25Retriever(bm25_documents)
        self.semantic_weight = semantic_weight
        self.bm25_weight = bm25_weight

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Dict[str, Any] = None,
        min_score: float = 0.0
    ) -> List[RetrievalResult]:
        """混合检索"""
        # 语义检索
        semantic_results = self.semantic_retriever.retrieve(
            query, top_k=top_k, filter_metadata=filter_metadata, min_score=min_score * 0.5
        )

        # BM25 检索
        bm25_results = self.bm25_retriever.retrieve(
            query, top_k=top_k, filter_metadata=filter_metadata, min_score=min_score * 0.3
        )

        # 合并结果
        combined: Dict[str, Dict] = {}

        for r in semantic_results:
            combined[r.id] = {
                'result': r,
                'semantic_score': r.score,
                'bm25_score': 0.0
            }

        for r in bm25_results:
            if r.id in combined:
                combined[r.id]['bm25_score'] = r.score
            else:
                combined[r.id] = {
                    'result': r,
                    'semantic_score': 0.0,
                    'bm25_score': r.score
                }

        # 计算综合分数
        results = []
        for doc_id, data in combined.items():
            semantic = data['semantic_score'] / max(self.semantic_weight, 0.01)
            bm25 = data['bm25_score'] / max(self.bm25_weight, 0.01)
            combined_score = (
                data['semantic_score'] * self.semantic_weight +
                data['bm25_score'] * self.bm25_weight
            )

            result = data['result']
            results.append(RetrievalResult(
                id=result.id,
                content=result.content,
                metadata=result.metadata,
                score=combined_score,
                query=query
            ))

        # 排序
        results.sort(key=lambda x: x.score, reverse=True)
        return results[:top_k]

    def update_bm25_documents(self, documents: List[Dict]):
        """更新 BM25 文档"""
        self.bm25_retriever.clear()
        self.bm25_retriever.add_documents(documents)
