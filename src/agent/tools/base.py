"""
工具基类定义
提供所有工具的统一抽象接口
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class ToolStatus(Enum):
    """工具执行状态"""
    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    execution_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "execution_time": self.execution_time
        }


class BaseTool(ABC):
    """
    工具抽象基类

    所有工具必须实现以下属性和方法：
    - name: 工具名称
    - description: 工具描述（用于LLM理解工具能力）
    - parameters: 参数模式定义
    - execute: 执行工具逻辑
    """

    def __init__(self):
        self._status = ToolStatus.IDLE

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称，必须唯一"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述，用于LLM理解工具能力和使用场景"""
        pass

    @property
    @abstractmethod
    def parameters(self) -> List[Dict[str, Any]]:
        """
        参数模式定义

        返回格式:
        [
            {
                "name": "参数名",
                "type": "string|number|boolean|array|object",
                "description": "参数描述",
                "required": true/false,
                "default": 默认值（可选）
            }
        ]
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """执行工具的核心逻辑"""
        pass

    def validate(self, **kwargs) -> bool:
        """
        执行前参数校验
        可被子类重写以实现自定义校验逻辑
        """
        required_params = [p["name"] for p in self.parameters if p.get("required", False)]
        for param in required_params:
            if param not in kwargs:
                return False
        return True

    @property
    def status(self) -> ToolStatus:
        """获取工具当前状态"""
        return self._status

    def reset(self):
        """重置工具状态"""
        self._status = ToolStatus.IDLE

    def get_schema(self) -> Dict[str, Any]:
        """
        获取工具的完整schema，用于LLM工具调用
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    p["name"]: {
                        "type": p["type"],
                        "description": p.get("description", "")
                    }
                    for p in self.parameters
                },
                "required": [p["name"] for p in self.parameters if p.get("required", False)]
            }
        }


class ToolMetadata:
    """工具元数据"""

    def __init__(
        self,
        name: str,
        description: str,
        category: str = "general",
        version: str = "1.0.0",
        tags: List[str] = None,
        examples: List[str] = None
    ):
        self.name = name
        self.description = description
        self.category = category
        self.version = version
        self.tags = tags or []
        self.examples = examples or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "tags": self.tags,
            "examples": self.examples
        }