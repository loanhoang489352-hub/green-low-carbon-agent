"""向后兼容垫片。

核心逻辑已迁移到 agent.routing(确定性状态机 + LLM 主路由)。
保留本模块让现有 import(agent.understanding.DemandInterpreter 等)继续工作。
"""
from agent.routing import (
    Demand,
    DialogueStateStore,
    DialogStateMachine,
    Router,
    DemandInterpreter,
    advance_state,
    mode_is_shadow,
)

__all__ = [
    'Demand',
    'DialogueStateStore',
    'DialogStateMachine',
    'Router',
    'DemandInterpreter',
    'advance_state',
    'mode_is_shadow',
]
