"""
工作记忆模块 (Working Memory, P4-H)

设计来源:ChatBI Agent 智能体方案 — 三段记忆(短期+工作+长期)
- 短期:单 session 对话历史(短期记忆的 5 轮滑动窗口 + 摘要)
- 工作(本模块):per-user 跨 session 的 workspace scope,多 key 共享状态
  - "AgenticScope" 模式:Agent 通过 set/get 读写命名空间
  - 同名 key 覆盖检测(防任务污染)
  - end_task 强制清空(否则污染下次任务)
  - OpenClaw 风格:自由写 + heartbeat 定期审计
- 长期:跨 session 永久(MEMORY.md 索引 + memory/*.md 详情),由 LongTermMemory 提供

工作记忆 vs 短期记忆:
| 维度   | 短期                 | 工作(本模块)            | 长期             |
|--------|---------------------|------------------------|------------------|
| 粒度   | 对话消息             | 命名空间 key-value     | 永久事实/偏好     |
| 范围   | 单 session          | per-user 跨 session    | 全局              |
| 容量   | 5 轮                | 不限,定期审计         | 索引 < 40 行     |
| 淘汰   | 旧轮次→摘要          | end_task 清空,过期 key 清理 | 半衰期 30 天衰减 |
| 持久化 | 内存(conversation)  | 内存 + JSON 快照        | SQLite            |

参考:图片集/4.jpg "Day36: 你的 AI Agent 为什么每次对话都'失忆'? 三层记忆模型彻底解决"
"""
from __future__ import annotations

import json
import re
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("memory.working")
except Exception:
    import logging
    _logger = logging.getLogger("memory.working")

project_root = Path(__file__).parent.parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

# ============================================================================
# 容量与 TTL
# ============================================================================

# 单用户 workspace 最大 key 数(超过会按 LRU 淘汰)
WORKSPACE_MAX_KEYS = 50
# 工作记忆 key 过期时间(小时,默认 24h;期间不活跃就清理)
WORKSPACE_TTL_HOURS = 24
# 同名 key 覆盖警告是否记录日志(开发期 True,生产可关)
LOG_OVERWRITE = True
# 可选:工作记忆 JSON 快照保存路径
WORKSPACE_SNAPSHOT_DIR = project_root / "data" / "memory_snapshots"


# ============================================================================
# 应否召回判断(should_recall):来自文章 Day36 "怎么判断要不要查记忆?"
# ============================================================================

# 明确信号:用户明确表示引用之前
EXPLICIT_RECALL_SIGNALS = (
    "上次", "之前", "前面", "昨天", "前天", "之前那次", "上次那个",
    "继续", "接着", "还记得", "你记得", "之前聊过", "我们说过",
    "刚才", "之前那个", "之前聊的", "以前",
)

# 隐式信号:需要上下文才能理解
IMPLICIT_RECALL_SIGNALS = (
    "那个", "那个方案", "换一下", "换成", "调整一下", "改一下",
    "第二个", "第N个", "再来一次", "类似", "同上次", "和上次一样",
    "跟上次", "和之前", "那个", "前面", "更早", "上次那个",
    "再试", "再聊聊", "用之前那个", "继续刚才",
)


def should_recall(user_input: str) -> bool:
    """判断用户输入是否需要召回记忆(短期/工作/长期)

    策略:扫描"上次/之前/继续"等明确信号词,或"那个/换成"等隐式信号词。
    明确信号 → 必查;隐式信号 → 1 个就触发(可调阈值)。

    Returns:
        True 表示应触发记忆召回(短期/工作/长期级联)
    """
    if not user_input:
        return False
    text = user_input.lower()
    for sig in EXPLICIT_RECALL_SIGNALS:
        if sig in text:
            return True
    implicit_hit = sum(1 for sig in IMPLICIT_RECALL_SIGNALS if sig in text)
    if implicit_hit >= 1:
        return True
    return False


# ============================================================================
# 工作记忆核心类
# ============================================================================


class _UserWorkspace:
    """单用户 workspace(线程安全)"""

    __slots__ = (
        "user_id",
        "scope",
        "task_log",
        "current_task",
        "last_active",
        "_lock",
    )

    def __init__(self, user_id: str):
        self.user_id = user_id
        # workspace scope: {key: {value, type, agent, updated_at, importance}}
        self.scope: Dict[str, Dict[str, Any]] = {}
        # 任务操作日志(用于审计 / 回溯)
        self.task_log: List[Dict[str, Any]] = []
        self.current_task: Optional[str] = None
        self.last_active: datetime = datetime.now()
        self._lock = threading.RLock()

    def touch(self) -> None:
        with self._lock:
            self.last_active = datetime.now()

    def size(self) -> int:
        with self._lock:
            return len(self.scope)

    def get(self, key: str) -> Any:
        with self._lock:
            entry = self.scope.get(key)
            if entry is None:
                return None
            entry["accessed_at"] = datetime.now().isoformat()
            entry["access_count"] = entry.get("access_count", 0) + 1
            return entry.get("value")

    def set(
        self,
        key: str,
        value: Any,
        agent_name: Optional[str] = None,
        importance: float = 0.5,
        overwrite: bool = True,
    ) -> bool:
        """设置 workspace key,带同名覆盖检测

        Args:
            key: 命名空间 key(如 "current_focus", "active_goal")
            value: 值
            agent_name: 写入 Agent 标识,用于审计
            importance: 0-1,影响淘汰优先级(高 importance 不易被清理)
            overwrite: 是否允许覆盖已有 key(默认 True)
        Returns:
            True 写入成功;False 因 overwrite=False 被拒
        """
        with self._lock:
            existing = self.scope.get(key)
            if existing is not None and not overwrite:
                return False
            overwritten = existing is not None
            if overwritten and LOG_OVERWRITE:
                old_agent = existing.get("agent", "?")
                old_value = existing.get("value")
                if old_value != value:
                    _logger.warning(
                        f"[WM:{self.user_id}] Agent {agent_name or '?'} "
                        f"覆盖了 key={key!r}(原 {old_agent})"
                    )
            self.scope[key] = {
                "value": value,
                "type": type(value).__name__,
                "agent": agent_name,
                "importance": max(0.0, min(1.0, importance)),
                "created_at": existing.get("created_at") if existing else datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "accessed_at": datetime.now().isoformat(),
                "access_count": existing.get("access_count", 0) if existing else 0,
            }
            self.task_log.append({
                "op": "set",
                "key": key,
                "agent": agent_name,
                "overwritten": overwritten,
                "timestamp": datetime.now().isoformat(),
            })
            if len(self.task_log) > 200:
                self.task_log = self.task_log[-200:]
            self.touch()
            return True

    def delete(self, key: str, agent_name: Optional[str] = None) -> bool:
        with self._lock:
            if key in self.scope:
                del self.scope[key]
                self.task_log.append({
                    "op": "delete",
                    "key": key,
                    "agent": agent_name,
                    "timestamp": datetime.now().isoformat(),
                })
                return True
            return False

    def keys(self, pattern: Optional[str] = None) -> List[str]:
        with self._lock:
            ks = list(self.scope.keys())
        if pattern:
            rx = re.compile(pattern)
            ks = [k for k in ks if rx.search(k)]
        return sorted(ks)

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "user_id": self.user_id,
                "current_task": self.current_task,
                "last_active": self.last_active.isoformat(),
                "scope": {k: dict(v) for k, v in self.scope.items()},
                "task_log_tail": self.task_log[-20:],
            }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """从 JSON 恢复 workspace"""
        with self._lock:
            self.current_task = data.get("current_task")
            try:
                la = data.get("last_active")
                if la:
                    self.last_active = datetime.fromisoformat(la)
            except (ValueError, TypeError):
                pass
            self.scope = {k: dict(v) for k, v in (data.get("scope") or {}).items()}
            # task_log 不持久化(仅审计用)


# ============================================================================
# WorkingMemory 单例
# ============================================================================


class WorkingMemory:
    """
    工作记忆管理器(单例,跨进程不安全,进程内线程安全)

    用法:
        wm = get_working_memory()
        wm.start_task("u_001", "onboarding")
        wm.set("u_001", "current_focus", "绿色出行", agent_name="nlu", importance=0.8)
        wm.set("u_001", "active_goal", {"title": "这周减塑", "progress": 0.3}, agent_name="planner")
        ctx = wm.snapshot_for_prompt("u_001")  # 给 LLM 用
        wm.end_task("u_001")
    """

    def __init__(self):
        self._workspaces: Dict[str, _UserWorkspace] = {}
        self._lock = threading.RLock()
        self._ensure_snapshot_dir()
        # 启动时从 JSON 快照恢复(如有)
        self._load_all_snapshots()

    def _ensure_snapshot_dir(self) -> None:
        try:
            WORKSPACE_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _get_workspace(self, user_id: str) -> _UserWorkspace:
        with self._lock:
            ws = self._workspaces.get(user_id)
            if ws is None:
                ws = _UserWorkspace(user_id)
                self._workspaces[user_id] = ws
            return ws

    # ---------------- 任务生命周期 ---------------- #

    def start_task(self, user_id: str, task_name: Optional[str] = None) -> None:
        """开始一个任务(task_name 用于审计/隔离)"""
        ws = self._get_workspace(user_id)
        with ws._lock:
            if ws.scope and LOG_OVERWRITE:
                _logger.warning(
                    f"[WM:{user_id}] 上次任务 workspace 仍有 {len(ws.scope)} 个 key,"
                    f" 先 end_task 再 start 避免污染"
                )
            ws.current_task = task_name
            ws.task_log.append({
                "op": "start_task",
                "task": task_name,
                "timestamp": datetime.now().isoformat(),
            })
            ws.touch()

    def end_task(self, user_id: str, clear: bool = True) -> None:
        """结束任务

        Args:
            clear: True(默认)清空 scope(防止下次任务污染)
                   False 保留 scope(用于跨任务共享状态)
        """
        ws = self._get_workspace(user_id)
        with ws._lock:
            ws.task_log.append({
                "op": "end_task",
                "task": ws.current_task,
                "clear": clear,
                "scope_size": len(ws.scope),
                "timestamp": datetime.now().isoformat(),
            })
            if clear:
                ws.scope = {}
            ws.current_task = None
            ws.touch()
        # 任务结束顺便保存快照
        self._save_snapshot(user_id)

    # ---------------- 命名空间操作 ---------------- #

    def set(
        self,
        user_id: str,
        key: str,
        value: Any,
        agent_name: Optional[str] = None,
        importance: float = 0.5,
    ) -> bool:
        ws = self._get_workspace(user_id)
        ok = ws.set(key, value, agent_name=agent_name, importance=importance)
        # 容量保护:超过 WORKSPACE_MAX_KEYS 触发 LRU 清理
        if ws.size() > WORKSPACE_MAX_KEYS:
            self._lru_evict(user_id, target=WORKSPACE_MAX_KEYS)
        # P6.D 修复:set 后落 JSON 快照(原版只在 end_task 保存,跨进程重启丢中间 set)
        self._save_snapshot(user_id)
        return ok

    def get(self, user_id: str, key: str, default: Any = None) -> Any:
        ws = self._get_workspace(user_id)
        v = ws.get(key)
        return v if v is not None else default

    def delete(self, user_id: str, key: str, agent_name: Optional[str] = None) -> bool:
        return self._get_workspace(user_id).delete(key, agent_name=agent_name)

    def keys(self, user_id: str, pattern: Optional[str] = None) -> List[str]:
        return self._get_workspace(user_id).keys(pattern)

    def snapshot(self, user_id: str) -> Dict[str, Any]:
        """整 workspace dict 快照(给 LLM prompt / 调试用)"""
        return self._get_workspace(user_id).to_dict()

    def snapshot_for_prompt(self, user_id: str) -> str:
        """生成给 LLM 用的工作记忆 prompt 片段(简洁形式)

        格式:
            [工作记忆]
            - current_focus: 绿色出行 (nlu, 重要性 0.80)
            - active_goal: {"title": "这周减塑", "progress": 0.3} (planner, 重要性 0.50)
        """
        ws = self._get_workspace(user_id)
        with ws._lock:
            items = sorted(
                ws.scope.items(),
                key=lambda kv: (kv[1].get("importance", 0.5), kv[1].get("updated_at", "")),
                reverse=True,
            )
        if not items:
            return ""
        lines = ["[工作记忆]"]
        for k, entry in items[:10]:  # 限制最多 10 条
            v = entry.get("value")
            if isinstance(v, (dict, list)):
                v_str = json.dumps(v, ensure_ascii=False)[:200]
            else:
                v_str = str(v)[:200]
            agent = entry.get("agent") or "?"
            imp = entry.get("importance", 0.5)
            lines.append(f"- {k}: {v_str} ({agent}, 重要性 {imp:.2f})")
        return "\n".join(lines)

    # ---------------- 维护 ---------------- #

    def _lru_evict(self, user_id: str, target: int) -> int:
        """按 importance + 最近访问 淘汰多余 key,直到 <= target"""
        ws = self._get_workspace(user_id)
        with ws._lock:
            if len(ws.scope) <= target:
                return 0
            # 排序:低 importance 且最久未访问的优先淘汰
            victims = sorted(
                ws.scope.items(),
                key=lambda kv: (
                    kv[1].get("importance", 0.5),
                    kv[1].get("accessed_at", kv[1].get("updated_at", "")),
                ),
            )
            evicted = 0
            for k, _ in victims:
                if len(ws.scope) <= target:
                    break
                del ws.scope[k]
                evicted += 1
            return evicted

    def cleanup_expired(self, ttl_hours: int = WORKSPACE_TTL_HOURS) -> int:
        """清理过期 key(超过 ttl_hours 未访问)"""
        cutoff = datetime.now() - timedelta(hours=ttl_hours)
        total = 0
        with self._lock:
            for user_id, ws in list(self._workspaces.items()):
                with ws._lock:
                    expired_keys = [
                        k for k, v in ws.scope.items()
                        if datetime.fromisoformat(
                            v.get("accessed_at", v.get("updated_at", datetime.now().isoformat()))
                        ) < cutoff
                        and v.get("importance", 0.5) < 0.8  # 重要的不淘汰
                    ]
                    for k in expired_keys:
                        del ws.scope[k]
                        total += 1
        return total

    def clear_user(self, user_id: str) -> None:
        """彻底清空某用户工作记忆(隐私删除)"""
        with self._lock:
            ws = self._workspaces.pop(user_id, None)
        if ws:
            snap = WORKSPACE_SNAPSHOT_DIR / f"{user_id}.json"
            if snap.exists():
                try:
                    snap.unlink()
                except Exception:
                    pass

    # ---------------- 快照持久化 ---------------- #

    def _snapshot_path(self, user_id: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", user_id)[:64]
        return WORKSPACE_SNAPSHOT_DIR / f"{safe}.json"

    def _save_snapshot(self, user_id: str) -> bool:
        try:
            ws = self._workspaces.get(user_id)
            if ws is None:
                return False
            data = ws.to_dict()
            self._snapshot_path(user_id).write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return True
        except Exception as e:
            if LOG_OVERWRITE:
                _logger.warning(f"[WM] 快照保存失败 {user_id}: {e}")
            return False

    def _load_all_snapshots(self) -> int:
        """启动时从 JSON 恢复"""
        if not WORKSPACE_SNAPSHOT_DIR.exists():
            return 0
        loaded = 0
        for f in WORKSPACE_SNAPSHOT_DIR.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                user_id = data.get("user_id") or f.stem
                ws = _UserWorkspace(user_id)
                ws.from_dict(data)
                self._workspaces[user_id] = ws
                loaded += 1
            except Exception as e:
                if LOG_OVERWRITE:
                    _logger.warning(f"[WM] 快照恢复失败 {f.name}: {e}")
        return loaded

    def list_users(self) -> List[str]:
        with self._lock:
            return list(self._workspaces.keys())

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "users": len(self._workspaces),
                "total_keys": sum(ws.size() for ws in self._workspaces.values()),
                "users_detail": {
                    uid: {
                        "keys": ws.size(),
                        "current_task": ws.current_task,
                        "last_active": ws.last_active.isoformat(),
                    }
                    for uid, ws in self._workspaces.items()
                },
            }


# ============================================================================
# 单例工厂
# ============================================================================

_working_memory_instance: Optional[WorkingMemory] = None
_working_memory_lock = threading.Lock()


def get_working_memory() -> WorkingMemory:
    """获取工作记忆单例(双检锁)"""
    global _working_memory_instance
    if _working_memory_instance is None:
        with _working_memory_lock:
            if _working_memory_instance is None:
                _working_memory_instance = WorkingMemory()
    return _working_memory_instance


def reset_working_memory() -> None:
    """重置单例(测试用)"""
    global _working_memory_instance
    with _working_memory_lock:
        _working_memory_instance = None
