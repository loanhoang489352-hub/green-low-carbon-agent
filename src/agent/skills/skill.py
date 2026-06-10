"""
Skill 抽象层
组合多个 BaseTool 形成高级技能
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

import sys
from pathlib import Path
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
sys.path.insert(0, str(project_root / 'src'))

from agent.tools.base import BaseTool, ToolResult, ToolStatus


@dataclass
class SkillContext:
    """Skill 执行上下文"""
    user_id: str = ""
    conversation_id: str = ""
    message: str = ""
    intent_type: str = ""
    profile: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    """
    Skill 抽象类

    Skill 是对 BaseTool 的组合封装，代表一个完整的业务能力。
    一个 Skill 可以组合多个 BaseTool，形成更高级的功能。

    例如：LowCarbonTravelSkill 组合了天气查询、路线规划、碳排放计算等多个工具
    """

    name: str = ""
    description: str = ""
    category: str = "general"

    @property
    @abstractmethod
    def tools(self) -> List[BaseTool]:
        """该 Skill 组合的工具列表"""
        pass

    @abstractmethod
    def execute(self, context: SkillContext) -> ToolResult:
        """
        执行 Skill

        Args:
            context: Skill 执行上下文

        Returns:
            ToolResult: 执行结果
        """
        pass

    def get_schema(self) -> Dict[str, Any]:
        """获取 Skill 的 schema（用于 LLM 理解）"""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tools": [t.name for t in self.tools]
        }

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """获取所有组合工具的 schema"""
        return [t.get_schema() for t in self.tools]


class SkillExecutor:
    """
    Skill 执行器

    负责 Skill 的注册和执行
    """

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill, overwrite: bool = False) -> bool:
        """注册 Skill"""
        if skill.name in self._skills and not overwrite:
            return False
        self._skills[skill.name] = skill
        return True

    def get(self, name: str) -> Optional[Skill]:
        """获取 Skill"""
        return self._skills.get(name)

    def list_all(self) -> List[str]:
        """列出所有已注册的 Skill"""
        return list(self._skills.keys())

    def execute(self, skill_name: str, context: SkillContext) -> ToolResult:
        """执行 Skill"""
        skill = self._skills.get(skill_name)
        if not skill:
            return ToolResult(
                success=False,
                error=f"Skill {skill_name} 不存在"
            )
        return skill.execute(context)

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Skill 的 schema"""
        return [s.get_schema() for s in self._skills.values()]


_global_skill_executor: Optional[SkillExecutor] = None


def get_skill_executor() -> SkillExecutor:
    """获取全局 Skill 执行器（单例）"""
    global _global_skill_executor
    if _global_skill_executor is None:
        _global_skill_executor = SkillExecutor()
    return _global_skill_executor