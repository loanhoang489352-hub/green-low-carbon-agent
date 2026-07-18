"""
Skill 模块
提供组合工具的高级技能抽象

P10.A:符合 Anthropic Skills 规范 — 含 version / when_to_use / allowed_tools
"""
from .skill import (
    Skill,
    SkillContext,
    SkillExecutor,
    SkillValidationError,
    get_skill_executor,
)

__all__ = [
    "Skill",
    "SkillContext",
    "SkillExecutor",
    "SkillValidationError",
    "get_skill_executor",
]