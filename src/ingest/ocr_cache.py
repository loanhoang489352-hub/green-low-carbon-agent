"""
OCR 缓存 — 按 content_hash 去重

目录结构:
    data/ocr_cache/<hash>.json

每个缓存文件:
{
  "content_hash": "sha256:...",
  "mime": "application/pdf" | "image/png" | ...,
  "source_url": "https://...",
  "engine": "paddleocr" | "aliyun" | "hybrid(mock)" | "pdfplumber",
  "confidence": 0.95,
  "page_count": 5,
  "text": "...",
  "saved_at": "2026-07-18T..."
}

设计原则:
- 写入失败不阻塞主路径(只记日志)
- hash 用 sha256(URL+content-length 或 URL+内容头部),简单稳
- 命中时直接返缓存内容,跳过 OCR
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from paths import DATA_DIR

logger = logging.getLogger(__name__)

OCR_CACHE_DIR: Path = DATA_DIR / "ocr_cache"


class OCRCache:
    """OCR 结果缓存(文件型)

    Args:
        cache_dir: 缓存目录,默认 data/ocr_cache/
    """

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else OCR_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Hash 工具
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_hash(content: bytes, mime: str = "") -> str:
        """sha256(content + mime) → 32 字符 hex

        mime 加入 hash 防止不同 MIME 同字节撞库
        """
        h = hashlib.sha256()
        h.update(content or b"")
        h.update((mime or "").encode("utf-8"))
        return h.hexdigest()[:32]

    @staticmethod
    def hash_url_with_meta(url: str, mime: str = "", length_hint: int = 0) -> str:
        """URL-only 场景的稳定 hash(用于抓回来的字节落地前先看缓存)"""
        h = hashlib.sha256()
        h.update((url or "").encode("utf-8"))
        h.update(b"|")
        h.update((mime or "").encode("utf-8"))
        h.update(b"|")
        h.update(str(length_hint).encode("utf-8"))
        return h.hexdigest()[:32]

    # ------------------------------------------------------------------ #
    # 读 / 写
    # ------------------------------------------------------------------ #
    def _path_for(self, content_hash: str) -> Path:
        return self.cache_dir / f"{content_hash}.json"

    def get(self, content_hash: str) -> Optional[Dict[str, Any]]:
        """命中缓存返回 dict;miss 返回 None"""
        if not content_hash:
            return None
        path = self._path_for(content_hash)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[OCRCache] 读缓存失败 %s: %s", path, exc)
            return None

    def put(self, payload: Dict[str, Any]) -> bool:
        """写入缓存;payload 必须含 content_hash 字段"""
        content_hash = payload.get("content_hash", "")
        if not content_hash:
            return False
        path = self._path_for(content_hash)
        try:
            with self._lock:
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return True
        except OSError as exc:
            logger.warning("[OCRCache] 写缓存失败 %s: %s", path, exc)
            return False

    def has(self, content_hash: str) -> bool:
        """轻量级存在性检查(不读 JSON)"""
        if not content_hash:
            return False
        return self._path_for(content_hash).exists()

    def clear(self) -> int:
        """清空缓存(测试用),返回删除的文件数"""
        count = 0
        try:
            for p in self.cache_dir.glob("*.json"):
                try:
                    p.unlink()
                    count += 1
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("[OCRCache] clear 失败: %s", exc)
        return count

    def stats(self) -> Dict[str, Any]:
        """缓存统计(大小 + 文件数)"""
        try:
            files = list(self.cache_dir.glob("*.json"))
            size_bytes = sum(p.stat().st_size for p in files if p.exists())
        except Exception:
            files = []
            size_bytes = 0
        return {
            "cache_dir": str(self.cache_dir),
            "file_count": len(files),
            "size_bytes": size_bytes,
        }


# 单例(便于 PolicyUpdater / KnowledgeUpdater 共享)
_cache_singleton: Optional[OCRCache] = None
_cache_lock = threading.Lock()


def get_ocr_cache() -> OCRCache:
    global _cache_singleton
    if _cache_singleton is None:
        with _cache_lock:
            if _cache_singleton is None:
                _cache_singleton = OCRCache()
    return _cache_singleton


def reset_ocr_cache() -> None:
    """测试用:重置单例"""
    global _cache_singleton
    with _cache_lock:
        _cache_singleton = None