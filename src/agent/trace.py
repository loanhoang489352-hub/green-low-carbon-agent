"""
agent.trace —— 智能体执行轨迹记录器(支持实时回调,用于 SSE 流式透明)

目的:让用户**实时**看到智能体的执行过程——识别了什么意图、检索了什么、
调用什么工具、LLM 在干嘛、每一步"进行中→完成"。

两种用法:
  1. 事后透明: Trace() → add(...) → trace.to_dict(),随响应返回,前端渲染"思考过程"。
  2. 实时透明: Trace(on_step=cb) → add()/start()/finish() 时回调 cb(entry),
     cb 把 entry 经 SSE 推给前端 → 前端边收边渲染成活的 timeline。

step 取值: intent / rag / memory / recommendations / llm / tool / skill /
          energy_planning / travel_planning / location / react / command / done / template
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


class Trace:
    """一次请求(一轮回答)的执行轨迹"""

    def __init__(self, on_step: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self.steps: List[Dict[str, Any]] = []
        self._on_step = on_step
        self._start_ts = datetime.utcnow()

    def _emit(self, entry: Dict[str, Any]) -> None:
        if self._on_step is not None:
            try:
                self._on_step(dict(entry))
            except Exception:
                pass

    def add(self, step: str, label: str, detail: Any = None, status: str = "done") -> int:
        """记录一步并(若有回调)实时发出。返回该步索引(便于后续 update 改成 done)。"""
        entry: Dict[str, Any] = {
            "step": step,
            "label": label,
            "status": status,
            "ts": datetime.utcnow().isoformat() + "Z",
        }
        if detail is not None:
            entry["detail"] = detail
        self.steps.append(entry)
        self._emit(entry)
        return len(self.steps) - 1

    def start(self, step: str, label: str, detail: Any = None) -> int:
        """新增一步,状态 running(实时体现在 '思考中…')。返回索引。"""
        return self.add(step, label, detail, status="running")

    def finish(self, index: int, detail: Any = None, status: str = "done") -> None:
        """把第 index 步从 running 改为 done(并实时重发)。避免"永远思考中"。”"""
        if 0 <= index < len(self.steps):
            self.steps[index]["status"] = status
            if detail is not None:
                self.steps[index]["detail"] = detail
            self._emit(self.steps[index])

    def update(self, index: int, status: Optional[str] = None, detail: Any = None) -> None:
        self.finish(index, detail=detail, status=status)

    def to_dict(self) -> List[Dict[str, Any]]:
        return [dict(s) for s in self.steps]

    def __len__(self) -> int:
        return len(self.steps)


__all__ = ["Trace"]
