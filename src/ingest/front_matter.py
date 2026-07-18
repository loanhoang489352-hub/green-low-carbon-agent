"""
Front-matter 渲染 — 落盘 markdown 文档时拼 YAML 头

格式:
---
ocr_engine: paddleocr|aliyun|hybrid(mock)|pdfplumber
ocr_confidence: 0.95
source_url: https://...
source_pdf: <原始 URL>     # 仅当上游是 PDF 链接
mime: application/pdf|image/png
page_count: 5
content_hash: sha256:xxxx
cached: true|false
ingested_at: 2026-07-18T...
---

# 标题
... 正文 ...
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def build_front_matter(meta: Dict[str, Any]) -> str:
    """把 dict 拼成 YAML front-matter 字符串(末尾带 ---)

    简单 YAML 序列化,支持 str/int/float/bool/None/list;
    字段值含特殊字符(: # 等)时用双引号转义。
    """
    if not meta:
        return ""
    lines: List[str] = ["---"]
    for key in sorted(meta.keys()):
        value = meta[key]
        if value is None:
            continue
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")  # 末尾空行,正文跟在后面
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    """轻量 YAML 标量序列化"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        # 简单 list: ["a", "b"] → [a, b]
        inner = ", ".join(_yaml_scalar(v) for v in value)
        return f"[{inner}]"
    if isinstance(value, str):
        # 含特殊字符时加双引号
        if any(c in value for c in [":", "#", "{", "}", "[", "]", "\n", '"']):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
        return value
    return str(value)


def build_document(
    title: str,
    body: str,
    *,
    ocr_engine: Optional[str] = None,
    ocr_confidence: Optional[float] = None,
    source_url: Optional[str] = None,
    source_pdf: Optional[str] = None,
    mime: Optional[str] = None,
    page_count: Optional[int] = None,
    content_hash: Optional[str] = None,
    cached: Optional[bool] = None,
    ingested_at: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """拼整篇文档(front-matter + 标题 + 正文)

    任何字段 None 都不出现在 front-matter 里
    """
    meta: Dict[str, Any] = {}
    if ocr_engine:
        meta["ocr_engine"] = ocr_engine
    if ocr_confidence is not None:
        meta["ocr_confidence"] = round(float(ocr_confidence), 4)
    if source_url:
        meta["source_url"] = source_url
    if source_pdf:
        meta["source_pdf"] = source_pdf
    if mime:
        meta["mime"] = mime
    if page_count is not None:
        meta["page_count"] = int(page_count)
    if content_hash:
        meta["content_hash"] = content_hash
    if cached is not None:
        meta["cached"] = bool(cached)
    meta["ingested_at"] = ingested_at or datetime.now().isoformat()
    if extra:
        for k, v in extra.items():
            if v is not None and k not in meta:
                meta[k] = v

    head = build_front_matter(meta)
    parts = [head, f"# {title}", "", body.strip(), ""]
    return "\n".join(parts)