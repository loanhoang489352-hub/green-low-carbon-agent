"""
工具注册表
提供工具的注册、发现、查询功能
"""

from typing import Dict, List, Optional
from .base import BaseTool, ToolMetadata


class ToolRegistry:
    """
    工具注册中心

    功能：
    - 注册工具（支持重复注册检查）
    - 按名称查找工具
    - 按类别查找工具
    - 列出所有可用工具
    - 工具调用前置校验
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._categories: Dict[str, List[str]] = {}  # category -> tool_names
        self._metadata: Dict[str, ToolMetadata] = {}

    def register(
        self, tool: BaseTool, metadata: ToolMetadata = None, overwrite: bool = False
    ) -> bool:
        """
        注册工具

        Args:
            tool: 工具实例
            metadata: 工具元数据（可选）
            overwrite: 是否覆盖已存在的工具

        Returns:
            是否注册成功
        """
        name = tool.name

        if name in self._tools and not overwrite:
            return False

        self._tools[name] = tool

        if metadata:
            self._metadata[name] = metadata
            category = metadata.category
            if category not in self._categories:
                self._categories[category] = []
            if name not in self._categories[category]:
                self._categories[category].append(name)

        return True

    def unregister(self, name: str) -> bool:
        """注销工具"""
        if name not in self._tools:
            return False

        tool = self._tools.pop(name)
        self._metadata.pop(name, None)

        # 从类别中移除
        for category_tools in self._categories.values():
            if name in category_tools:
                category_tools.remove(name)

        return True

    def get(self, name: str) -> Optional[BaseTool]:
        """根据名称获取工具"""
        return self._tools.get(name)

    def get_by_category(self, category: str) -> List[BaseTool]:
        """获取指定类别的所有工具"""
        tool_names = self._categories.get(category, [])
        return [self._tools[name] for name in tool_names if name in self._tools]

    def list_all(self) -> List[str]:
        """列出所有已注册的工具名称"""
        return list(self._tools.keys())

    def list_by_tag(self, tag: str) -> List[str]:
        """根据标签查找工具"""
        result = []
        for name, meta in self._metadata.items():
            if tag in meta.tags:
                result.append(name)
        return result

    def get_metadata(self, name: str) -> Optional[ToolMetadata]:
        """获取工具元数据"""
        return self._metadata.get(name)

    def validate_tool(self, name: str, **kwargs) -> tuple[bool, Optional[str]]:
        """
        校验工具参数

        Returns:
            (is_valid, error_message)
        """
        tool = self._tools.get(name)
        if not tool:
            return False, f"工具 {name} 不存在"

        if not tool.validate(**kwargs):
            required = [p["name"] for p in tool.parameters if p.get("required", False)]
            missing = [p for p in required if p not in kwargs]
            if missing:
                return False, f"缺少必需参数: {', '.join(missing)}"

        return True, None

    def get_all_schemas(self) -> List[Dict]:
        """获取所有工具的schema，用于LLM工具调用"""
        return [tool.get_schema() for tool in self._tools.values()]

    def exists(self, name: str) -> bool:
        """检查工具是否已注册"""
        return name in self._tools

    def count(self) -> int:
        """获取已注册工具数量"""
        return len(self._tools)

    def clear(self):
        """清空所有已注册的工具"""
        self._tools.clear()
        self._categories.clear()
        self._metadata.clear()


# 全局工具注册表实例
_global_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """获取全局工具注册表实例（单例）"""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def register_tool(tool: BaseTool, metadata: ToolMetadata = None) -> bool:
    """快速注册工具到全局注册表"""
    return get_registry().register(tool, metadata)


def get_tool(name: str) -> Optional[BaseTool]:
    """快速从全局注册表获取工具"""
    return get_registry().get(name)
