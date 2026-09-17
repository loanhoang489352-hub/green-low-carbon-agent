# plugins/core_tools.py
"""
内置工具插件 —— 把核心工具挂到插件系统,实现"核心零硬编码能力"。

迁移自 src/server/app.py::_register_all_tools_and_skills 的硬编码注册。
新增/替换工具,直接改这个插件即可,核心代码不再涉及工具清单。
"""
from __future__ import annotations

from agent.tools.extended import (
    TravelPlanningTool,
    KnowledgeRetrievalTool,
    CarbonFootprintTool,
    ReportExportTool,
)
from agent.skills.energy_planning_skill import (
    HouseholdProfileTool,
    EnergyPlannerTool,
    EnergyActionTrackerTool,
)


# (ToolClass, category, tags) —— 与旧硬编码清单一一对应
TOOLS = [
    (TravelPlanningTool, "travel", ["navigation", "carbon", "weather"]),
    (KnowledgeRetrievalTool, "knowledge", ["rag", "search"]),
    (CarbonFootprintTool, "carbon", ["calculation", "footprint"]),
    (ReportExportTool, "report", ["export", "pdf"]),
    (HouseholdProfileTool, "energy", ["household", "profile", "energy"]),
    (EnergyPlannerTool, "energy", ["plan", "saving", "energy"]),
    (EnergyActionTrackerTool, "energy", ["track", "completion", "energy"]),
]


def register(api) -> None:
    for ToolCls, cat, tags in TOOLS:
        api.register_tool(ToolCls(), category=cat, tags=tags)
