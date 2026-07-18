"""
P8.R1: BGE Reranker 模块

使用 BAAI/bge-reranker-base 对检索结果做精排,提升 RAG 召回质量。

设计要点:
- 懒加载:首次 rerank() 调用时加载模型(~30s),之后复用
- enabled 开关:关闭时 rerank() 直接返回原序(向后兼容)
- 错误容错:模型加载/推理失败 → 回退原序,不阻塞主流程
- 静态接口:Reranker.rerank(query, results, top_k) → results
  与现有 RAGEngine.retrieve() 签名解耦,可独立测试
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

# Windows UTF-8
import sys

if sys.platform == "win32":
    import io

    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 本地导入
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

# logger
try:
    from observability import get_logger

    _logger = get_logger("rag.reranker")
except Exception:
    import logging

    _logger = logging.getLogger("rag.reranker")


@dataclass
class RerankConfig:
    """Rerank 配置"""

    enabled: bool = True
    model_name: str = "BAAI/bge-reranker-base"
    top_k_input: int = 20  # 初始召回候选数
    top_k_output: int = 5  # 最终输出数
    use_fp16: bool = False  # FP16(需 GPU)
    max_length: int = 512
    batch_size: int = 32


class Reranker:
    """
    BGE Reranker 封装

    用法:
        reranker = Reranker(RerankConfig(enabled=True))
        ranked = reranker.rerank(query, results, top_k=5)
        # ranked 是 List[RetrievalResult],按 rerank score 降序

    失败容错:
        - 模型加载失败 → 返回原序,设置 self.enabled=False
        - 推理异常 → 返回原序,记录日志

    性能:
        - 首次加载: ~30s(从 HuggingFace 下载 ~280MB + 加载)
        - 推理: ~50-150ms / 批 20 条(CPU)
    """

    _model_lock = threading.Lock()  # 跨实例共享,避免重复加载

    def __init__(self, config: Optional[RerankConfig] = None):
        self.config = config or RerankConfig()
        self._model: Any = None  # FlagReranker
        self._load_attempted: bool = False
        self._load_error: Optional[str] = None
        # 统计
        self.stats = {
            "total_calls": 0,
            "total_rerank_ms": 0.0,
            "avg_rerank_ms": 0.0,
            "fail_count": 0,
        }

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        """显式加载模型(可选;rerank() 也会自动触发)

        Returns:
            True 加载成功 / False 加载失败(之后 rerank() 走降级)
        """
        if self._model is not None:
            return True
        if self._load_attempted and self._load_error:
            return False

        with self._model_lock:
            if self._model is not None:
                return True
            self._load_attempted = True
            try:
                from FlagEmbedding import FlagReranker

                # P8.R1: 大陆 IP 可能 huggingface.co 不通,设 HF_HUB_OFFLINE=1 优先用本地缓存
                # 也允许通过 RERANK_MODEL_PATH 环境变量覆盖模型路径
                model_path = os.environ.get("RERANK_MODEL_PATH", self.config.model_name)

                t0 = time.time()
                _logger.info(
                    "[reranker] 加载模型 %s (fp16=%s)...",
                    model_path,
                    self.config.use_fp16,
                )
                self._model = FlagReranker(
                    model_path,
                    use_fp16=self.config.use_fp16,
                    max_length=self.config.max_length,
                )
                load_ms = (time.time() - t0) * 1000
                _logger.info("[reranker] 模型加载完成 (%.0f ms)", load_ms)
                return True
            except Exception as e:
                self._load_error = str(e)
                _logger.warning("[reranker] 模型加载失败,rerank 降级到原序: %s", e)
                return False

    def rerank(
        self,
        query: str,
        results: List[Any],
        top_k: Optional[int] = None,
    ) -> List[Any]:
        """
        对检索结果做精排

        Args:
            query: 原始查询
            results: 候选结果列表(每个元素有 .content / .score 字段)
            top_k: 返回 top_k(默认用 config.top_k_output)

        Returns:
            重排后的结果列表(按 rerank score 降序)
        """
        if not results:
            return results
        if top_k is None:
            top_k = self.config.top_k_output
        if not self.config.enabled:
            # 禁用时仍按 top_k 截断(行为一致,便于上层无脑调用)
            return results[:top_k]

        # 懒加载模型
        if self._model is None:
            ok = self.load()
            if not ok or self._model is None:
                # 降级:返回原序
                return results[:top_k]

        try:
            t0 = time.time()
            # 构造 (query, doc) 对
            pairs = [(query, getattr(r, "content", "") or "") for r in results]

            # FlagReranker.compute_score 返回 List[float],与原序一一对应
            scores = self._model.compute_score(
                pairs, batch_size=self.config.batch_size, normalize=True
            )
            # 兼容:compute_score 在单对时返回 float
            if isinstance(scores, float):
                scores = [scores]

            # 按 rerank score 降序重排
            indexed = list(enumerate(results))
            indexed.sort(key=lambda x: float(scores[x[0]]), reverse=True)
            ranked = [r for _, r in indexed]

            # 写回新 score(让后续 post_filter / metrics 看到 rerank 分)
            for i, (orig_idx, _) in enumerate(indexed):
                ranked[i].score = float(scores[orig_idx])

            elapsed = (time.time() - t0) * 1000
            self.stats["total_calls"] += 1
            self.stats["total_rerank_ms"] += elapsed
            self.stats["avg_rerank_ms"] = (
                self.stats["total_rerank_ms"] / self.stats["total_calls"]
            )

            return ranked[:top_k]

        except Exception as e:
            self.stats["fail_count"] += 1
            _logger.warning("[reranker] rerank 失败,回退原序: %s", e)
            return results[:top_k]

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            **self.stats,
            "is_loaded": self.is_loaded,
            "enabled": self.config.enabled,
            "model_name": self.config.model_name,
            "load_error": self._load_error,
        }


# 单例(供 RAGEngine 启动时注入)
_reranker_instance: Optional[Reranker] = None
_reranker_lock = threading.Lock()


def get_reranker(config: Optional[RerankConfig] = None) -> Reranker:
    """获取 reranker 单例(首次传 config 生效,之后忽略)"""
    global _reranker_instance
    if _reranker_instance is None:
        with _reranker_lock:
            if _reranker_instance is None:
                _reranker_instance = Reranker(config or RerankConfig())
    return _reranker_instance


def reset_reranker() -> None:
    """重置单例(测试用)"""
    global _reranker_instance
    with _reranker_lock:
        _reranker_instance = None