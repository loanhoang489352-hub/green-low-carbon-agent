"""
文本嵌入器 - 将文本转换为向量
支持多种嵌入模型
"""

import sys
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

from typing import List, Union
import numpy as np

# P5-F: 模块级 logger
try:
    from observability import get_logger

    _logger = get_logger("rag.embedder")
except Exception:
    import logging

    _logger = logging.getLogger("rag.embedder")


class Embedder:
    """文本嵌入器基类"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.model_name = model_name
        self._model = None
        self._dimension = None

    @property
    def dimension(self) -> int:
        """获取向量维度"""
        if self._dimension is None:
            self._ensure_model_loaded()
        return self._dimension

    def _ensure_model_loaded(self):
        """延迟加载模型"""
        if self._model is None:
            self._load_model()

    def _load_model(self):
        """加载嵌入模型 - 子类实现"""
        raise NotImplementedError

    def encode(self, texts: Union[str, List[str]]) -> np.ndarray:
        """编码文本为向量"""
        self._ensure_model_loaded()
        if isinstance(texts, str):
            texts = [texts]
        return self._encode_impl(texts)

    def _encode_impl(self, texts: List[str]) -> np.ndarray:
        """实际的编码实现 - 子类实现"""
        raise NotImplementedError

    def similarity(self, text1: str, text2: str) -> float:
        """计算两个文本的相似度"""
        vec1 = self.encode(text1)
        vec2 = self.encode(text2)
        return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))


class SentenceTransformerEmbedder(Embedder):
    """使用 sentence-transformers 的嵌入器"""

    def __init__(self, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        super().__init__(model_name)
        self._load_attempted = False
        self._use_fallback = False

    def _load_model(self):
        """加载 sentence-transformers 模型"""
        if self._load_attempted:
            # 已经尝试过加载，不要重复尝试
            return

        self._load_attempted = True

        try:
            from sentence_transformers import SentenceTransformer

            print(f"[嵌入器] 正在加载模型: {self.model_name}")
            print("[嵌入器] 首次使用需要下载模型（约100MB），请耐心等待...")
            self._model = SentenceTransformer(self.model_name)
            new_dim = self._model.get_sentence_embedding_dimension()
            self._dimension = new_dim
            print(f"[嵌入器] 模型加载完成 (维度: {new_dim})")
        except Exception as e:
            print(f"[嵌入器] 模型加载失败: {e}")
            # 检查是否只是部分失败（模型已加载但获取维度失败）
            if self._model is not None:
                self._dimension = 384
                print("[嵌入器] 使用备用维度: 384")
            else:
                self._use_fallback = True
                self._dimension = 384  # 默认维度
                print("[嵌入器] 使用简单嵌入作为备用方案")

    def _encode_impl(self, texts: List[str]) -> np.ndarray:
        """使用 sentence-transformers 编码"""
        if self._model is None:
            return self._simple_encode(texts)
        return self._model.encode(texts, convert_to_numpy=True)

    def _simple_encode(self, texts: List[str]) -> np.ndarray:
        """简单的基于词的编码（降级方案）- 生成固定维度向量"""
        dim = self._dimension
        vectors = []
        for text in texts:
            # 简单的词袋模型，映射到固定维度
            words = set(text.lower().split())
            vec = np.zeros(dim)
            for word in words:
                # 使用简单的哈希函数确保稳定
                idx = hash(word) % dim
                vec[idx] = 1.0
            vectors.append(vec)

        # 返回正确的形状：(n_texts, dim)
        result = np.array(vectors)
        # 确保是2D数组
        if result.ndim == 1:
            result = result.reshape(1, -1)
        return result


class OpenAIEmbedder(Embedder):
    """使用 OpenAI API 的嵌入器"""

    def __init__(self, api_key: str = None, model: str = "text-embedding-3-small"):
        super().__init__(model)
        self.api_key = api_key
        self.model = model

    def _load_model(self):
        """初始化 OpenAI 客户端"""
        try:
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key)
            self._dimension = 1536 if "3-small" in self.model else 3072
            print(f"[OK] OpenAI 嵌入模型初始化完成 (维度: {self._dimension})")
        except ImportError:
            _logger.warning("openai 包未安装")
            self._client = None

    def _encode_impl(self, texts: List[str]) -> np.ndarray:
        """使用 OpenAI API 编码"""
        if self._client is None:
            return np.random.randn(len(texts), self._dimension)

        embeddings = []
        for text in texts:
            response = self._client.embeddings.create(model=self.model, input=text)
            embeddings.append(response.data[0].embedding)

        return np.array(embeddings)


def create_embedder(
    provider: str = "sentence-transformers",
    model_name: str = "paraphrase-multilingual-MiniLM-L12-v2",
    api_key: str = None,
) -> Embedder:
    """工厂函数：创建嵌入器"""
    if provider == "openai":
        return OpenAIEmbedder(api_key=api_key)
    else:
        return SentenceTransformerEmbedder(model_name=model_name)
