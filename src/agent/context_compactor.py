"""
Context 压缩 + token 预算(P16)

解决长对话"爆窗":
  现状:对话历史按条数硬截断(MAX_CONVERSATION_LENGTH=50),无 token 预算、无摘要折叠。
  本模块:
    - estimate_tokens  : 粗略 token 估算(CJK 每字 ≈ 1 token,其余每 4 字符 ≈ 1 token)
    - ContextBudget    : 各上下文块的 token 配额(历史/RAG/画像/工具/system/reserve)
    - compact_history  : 按 token 预算保留最近轮次,更早轮次折叠为摘要占位

纯逻辑、零 LLM 依赖,可单测。滚动摘要的生成(需 LLM)留给调用方按 needs_summary
标志异步补做 —— 本模块只负责"决定保留什么、折叠什么"。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def estimate_tokens(text: str) -> int:
    """粗略 token 估算:中文每字 ≈ 1 token,其余每 4 字符 ≈ 1 token。

    精确计数依赖 tokenizer,这里用 O(1) 启发式,只用于预算判断(够用)。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return cjk + (other // 4) + 1


def _message_tokens(msg: Any) -> int:
    """单条消息的 token 估算(含 role/格式开销)"""
    if isinstance(msg, dict):
        content = str(msg.get("content", "") or "")
    else:
        content = str(msg)
    return estimate_tokens(content) + 4


@dataclass
class ContextBudget:
    """各上下文块的 token 配额(保守值,兼容 6k 窗口小模型)"""

    total: int = 6000
    history: int = 1600      # 对话历史
    rag: int = 1000          # RAG 检索上下文
    profile: int = 300       # 用户画像
    tools: int = 800         # 工具 schema
    system: int = 700        # persona + 护栏 + 规则
    reserve: int = 800       # 输出 + 安全余量

    @property
    def allocated(self) -> int:
        """除 reserve 外的已分配配额之和"""
        return self.history + self.rag + self.profile + self.tools + self.system


@dataclass
class CompactedHistory:
    kept: List[Dict[str, Any]]
    summary: str
    dropped_turns: int
    needs_summary: bool

    def tokens(self) -> int:
        return sum(_message_tokens(m) for m in self.kept) + estimate_tokens(self.summary)


def compact_history(
    history: List[Dict[str, Any]],
    budget_tokens: int,
    summary: str = "",
    keep_last_n: int = 6,
) -> CompactedHistory:
    """按 token 预算压缩对话历史。

    策略:
      1. 总是保留最近 keep_last_n 条(不丢当前上下文)。
      2. 从最旧往新填,直到超出 budget_tokens 为止。
      3. 更早的轮次折叠进 summary;若尚未有摘要且发生了折叠,标记 needs_summary。

    Args:
        history: 完整历史(role/content 列表)
        budget_tokens: 历史块配额(如 ContextBudget().history)
        summary: 已有的滚动摘要(为空表示尚未摘要)
        keep_last_n: 无论如何保留的最近条数

    Returns:
        CompactedHistory(kept, summary, dropped_turns, needs_summary)
    """
    if not history:
        return CompactedHistory([], summary, 0, False)

    n = len(history)

    # 尾巴(最近 keep_last_n 条)无论如何保留
    tail = history[-keep_last_n:] if n > keep_last_n else list(history)
    tail_tokens = sum(_message_tokens(m) for m in tail)

    # 尾巴本身超预算 → 从最新往前保,但永远至少保留最近一条
    if tail_tokens > budget_tokens:
        kept: List[Dict[str, Any]] = []
        used = 0
        for m in reversed(history):
            t = _message_tokens(m)
            # 已有内容时,再加会超预算就停;第一条无论如何保留(截断到预算内)
            if kept and used + t > budget_tokens:
                break
            kept.insert(0, m)
            used += t
        dropped = n - len(kept)
        return CompactedHistory(kept, summary, dropped, dropped > 0 and not summary)

    # 正常路径:尾巴 + 从最旧往前填头部
    kept = list(tail)
    used = tail_tokens
    head = history[: n - len(tail)]
    for m in reversed(head):
        t = _message_tokens(m)
        if used + t > budget_tokens:
            break
        kept.insert(0, m)
        used += t

    dropped = n - len(kept)
    return CompactedHistory(kept, summary, dropped, dropped > 0 and not summary)


def compact_rag(
    docs: List[Dict[str, Any]],
    budget_tokens: int,
    max_content_chars: int = 500,
) -> List[Dict[str, Any]]:
    """按 token 预算截断 RAG 文档列表(截断单条 content,不丢文档数)。

    Args:
        docs: RAG 结果列表(含 content 字段)
        budget_tokens: RAG 配额
        max_content_chars: 单条 content 最大字符数
    """
    if not docs:
        return docs
    out: List[Dict[str, Any]] = []
    used = 0
    per_doc = max(1, budget_tokens // len(docs))
    for d in docs:
        content = str(d.get("content", "") or "")[:max_content_chars]
        if estimate_tokens(content) > per_doc:
            # 按 token 配额截断 content
            target_chars = per_doc * 4  # 近似:1 token ≈ 4 字符(中文更省)
            content = content[:target_chars]
        used += estimate_tokens(content)
        if used > budget_tokens and out:
            break
        out.append({**d, "content": content})
    return out


__all__ = [
    "estimate_tokens",
    "ContextBudget",
    "CompactedHistory",
    "compact_history",
    "compact_rag",
]
