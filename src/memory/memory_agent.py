"""
三层记忆级联召回 (P4-H)

设计思想:三层不是叠加而是级联 — 短期优先 → 工作补充 → 长期兜底。
能用免费的就用免费的,这跟写代码先查缓存再查数据库是一个道理。

来自:图片集/4.jpg "Day36 整合三层:MemoryAgent 级联查询闭环"
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).parent.parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

from memory.short_term import get_short_term_memory
from memory.working import get_working_memory, should_recall


# 三层召回源标识
SOURCE_SHORT_TERM = "short_term"
SOURCE_WORKING = "working"
SOURCE_LONG_TERM = "long_term"


def cascaded_recall(
    user_id: str,
    query: str,
    conversation_id: Optional[str] = None,
    *,
    short_limit: int = 5,
    long_limit: int = 3,
    force_long: bool = False,
) -> Dict[str, Any]:
    """
    级联召回:短期 → 工作 → 长期,免费的先用

    流程:
      1. should_recall(query) == False 且非 force_long → 仅短期(零成本)
      2. 短期:从 conversation 取最近 N 轮
      3. 工作:从 working memory scope 取 key-value(如 active_goal, current_focus)
      4. 长期:query 经关键词提取后查 long_term.search_memories(有 embedding 成本)

    Returns:
        {
            "should_recall": bool,
            "short_term": [...],     # 对话历史(免费)
            "working": [...],        # workspace scope(免费)
            "long_term": [...],      # long_term 召回(有成本)
            "merged_for_prompt": str # 注入 LLM 的统一文本
        }
    """
    need_recall = should_recall(query) or force_long

    # 1) 短期(总是返回,零成本)
    short_msgs: List[Dict[str, Any]] = []
    if conversation_id:
        try:
            stm = get_short_term_memory()
            short_msgs = stm.get_conversation_history(conversation_id, limit=short_limit)
        except Exception:
            pass

    # 2) 工作(总是返回,零成本)
    working_items: List[Dict[str, Any]] = []
    try:
        wm = get_working_memory()
        snap = wm.snapshot(user_id)
        for k, entry in (snap.get("scope") or {}).items():
            working_items.append({
                "key": k,
                "value": entry.get("value"),
                "importance": entry.get("importance", 0.5),
                "agent": entry.get("agent"),
            })
    except Exception:
        pass

    # 3) 长期(仅在需要时)
    long_items: List[Dict[str, Any]] = []
    if need_recall:
        try:
            from memory.long_term import LongTermMemory
            lt = LongTermMemory()
            long_items = lt.search_memories(user_id, query, limit=long_limit)
        except Exception:
            pass

    # 4) 合并到 prompt
    prompt_parts: List[str] = []
    if short_msgs:
        short_text = "\n".join(
            f"{m.get('role', '?')}: {m.get('content', '')[:200]}"
            for m in short_msgs[-short_limit:]
        )
        prompt_parts.append(f"[短期记忆(最近对话)]\n{short_text}")
    if working_items:
        ws_text = "\n".join(
            f"- {it['key']}: {it['value']} (importance={it['importance']:.2f})"
            for it in working_items[:8]
        )
        prompt_parts.append(f"[工作记忆(workspace)]\n{ws_text}")
    if long_items:
        lt_text = "\n".join(
            f"- {it.get('content', str(it))[:200]}"
            for it in long_items[:long_limit]
        )
        prompt_parts.append(f"[长期记忆(相关历史)]\n{lt_text}")

    return {
        "should_recall": need_recall,
        "short_term": short_msgs,
        "working": working_items,
        "long_term": long_items,
        "merged_for_prompt": "\n\n".join(prompt_parts),
    }


def promote_working_to_long_term(
    user_id: str,
    key: str,
    *,
    importance_threshold: float = 0.7,
) -> bool:
    """
    把工作记忆里高 importance 的 key 晋升到长期记忆
    (OpenClaw 风格的"定期审计":agent 自由写,heartbeat 整理时把重要的固化)
    """
    try:
        wm = get_working_memory()
        entry = wm.get(user_id, key)
        if entry is None:
            return False
        # 重要性需 >= 阈值才晋升
        snap = wm.snapshot(user_id)
        meta = (snap.get("scope") or {}).get(key) or {}
        if meta.get("importance", 0.5) < importance_threshold:
            return False
        from memory.long_term import LongTermMemory
        lt = LongTermMemory()
        content = f"[{key}] {entry}"
        lt.add_memory(
            user_id=user_id,
            content=content,
            memory_type="working_promotion",
            importance=meta.get("importance", 0.5),
        )
        return True
    except Exception:
        return False
