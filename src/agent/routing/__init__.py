"""路由层:确定性状态机 + LLM 主路由。

结构:
  - demand.py         需求数据结构(Demand)+ 状态推进 + 对话状态存储
  - patterns.py       领域关键词正则(状态机与路由器共用)
  - state_machine.py  确定性对话状态机(cancel / resume / continue / 填槽 / 多任务)
  - router.py         需求路由器(状态机 → 关键词前置 → LLM 主路由 → 关键词兜底)
"""
from .demand import Demand, DialogueStateStore, advance_state, mode_is_shadow
from .patterns import domain_of, planning_intent
from .state_machine import DialogStateMachine
from .router import Router

# 向后兼容别名:旧代码从 agent.understanding 导入 DemandInterpreter
DemandInterpreter = Router

__all__ = [
    'Demand',
    'DialogueStateStore',
    'advance_state',
    'mode_is_shadow',
    'domain_of',
    'planning_intent',
    'DialogStateMachine',
    'Router',
    'DemandInterpreter',
]
