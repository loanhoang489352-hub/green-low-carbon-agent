# plugins/core_skills.py
"""
内置技能插件 —— 把核心 Skill 挂到插件系统。

迁移自 src/server/app.py::_register_all_tools_and_skills 的硬编码 skill 注册。
"""
from __future__ import annotations

from agent.skills.builtin import (
    LowCarbonTravelSkill,
    PolicyQuerySkill,
    ProfileUpdateSkill,
)
from agent.skills.energy_planning_skill import EnergyPlanningSkill


SKILLS = [LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill, EnergyPlanningSkill]


def register(api) -> None:
    for SkillCls in SKILLS:
        api.register_skill(SkillCls())
