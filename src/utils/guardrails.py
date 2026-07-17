"""
任务6: 轻量级输入/输出 Guardrails
基于 config/guardrails.yaml 的规则式过滤
- 关键词黑名单(jailbreak + 有害内容)
- 长度限制
- PII 自动脱敏(已有 utils/pii.py)
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict, Tuple

_GUARDRAILS_PATH = Path(__file__).parent.parent.parent / "config" / "guardrails.yaml"
_CONFIG_CACHE: Dict[str, Any] | None = None


def load_guardrails_config() -> Dict[str, Any]:
    """加载 guardrails 配置(单例 + lru_cache 风格)"""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    if not _GUARDRAILS_PATH.exists():
        _CONFIG_CACHE = {"input_filters": {}, "output_filters": {}, "mode": "rule-only"}
        return _CONFIG_CACHE
    with open(_GUARDRAILS_PATH, encoding="utf-8") as f:
        _CONFIG_CACHE = yaml.safe_load(f) or {}
    return _CONFIG_CACHE


def check_input(text: str) -> Tuple[bool, str]:
    """检查输入文本是否通过守门员

    Returns:
        (passed, reason) — passed=True 表示通过;否则 reason 说明被拦截原因
    """
    cfg = load_guardrails_config()
    inp = cfg.get("input_filters", {})

    # 0) 防御性 None/非 str 检查
    if not isinstance(text, str):
        return False, "输入非字符串类型"
    if not text:
        return True, ""  # 空串放行(给上层逻辑决定)

    # 1) 长度检查
    max_len = inp.get("max_length", 2000)
    if len(text) > max_len:
        return False, f"输入超长({len(text)}>{max_len})"

    # 2) 关键词黑名单
    text_lower = text.lower()
    for kw in inp.get("forbidden_keywords", []):
        if kw.lower() in text_lower:
            return False, f"包含禁用关键词:{kw}"

    # 3) jailbreak 模式
    for pat in inp.get("jailbreak_patterns", []):
        if pat.lower() in text_lower:
            return False, f"疑似越狱模式:{pat}"

    return True, ""


def check_output(text: str) -> Tuple[bool, str]:
    """检查输出文本是否合规

    Returns:
        (passed, reason)
    """
    cfg = load_guardrails_config()
    out = cfg.get("output_filters", {})

    # 1) 长度检查
    max_len = out.get("max_length", 5000)
    if len(text) > max_len:
        return False, f"输出超长({len(text)}>{max_len})"

    # 2) 必含关键词(可选)
    min_kw = out.get("required_keywords_min_count", 0)
    if min_kw > 0:
        green = out.get("green_keywords", [])
        hits = sum(1 for k in green if k in text.lower())
        if hits < min_kw:
            return False, f"输出与绿色低碳主题不相关(命中 {hits}/{min_kw} 关键词)"

    return True, ""


def redact_pii(text: str) -> str:
    """对输出做 PII 脱敏(用 utils.pii)"""
    if not text:
        return text
    try:
        from utils.pii import mask_pii

        return mask_pii(text)
    except Exception:
        return text


def guardrail_input(text: str) -> Tuple[bool, str, str]:
    """任务6 顶层入口 — 输入守门

    Returns:
        (passed, reason, sanitized_text)
        sanitized_text 是脱敏/裁剪后的输入(目前 = 原 text)
    """
    passed, reason = check_input(text)
    return passed, reason, text


def guardrail_output(text: str) -> Tuple[bool, str, str]:
    """任务6 顶层入口 — 输出守门

    Returns:
        (passed, reason, sanitized_text) — sanitized 已脱敏
    """
    passed, reason = check_output(text)
    sanitized = redact_pii(text) if passed else text
    return passed, reason, sanitized
