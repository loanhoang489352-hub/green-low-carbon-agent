# plugins/example_plugin.py
"""
示例插件:演示"插件式"架构。
把这一个 .py 放进 plugins/ 目录,重启服务即自动挂载,无需改任何核心代码。

契约: 提供模块级 `register(api)`,用 api 注册工具/技能/路由。
"""
from __future__ import annotations

import random
import time
from typing import Dict, List, Any

from agent.tools.base import BaseTool, ToolResult


TIPS = [
    "短期不开车,5公里内骑行或步行,既省油又健身。",
    "空调夏天设 26℃、冬天设 20℃,一年可省数百元电费。",
    "自带购物袋,减少一次性塑料袋,顺手又环保。",
    "热水器避开用电高峰(22 点后),用谷段电价更省钱。",
    "冰箱冷藏 4℃、冷冻 -18℃,别频繁开门,更省电。",
    "洗菜水留着冲厕所,一水多用,节水又省钱。",
]


class DailyEcoTipTool(BaseTool):
    """来源:绿色低碳智能体示例插件 — 每日一条低碳小贴士"""

    @property
    def name(self) -> str:
        return "daily_eco_tip"

    @property
    def description(self) -> str:
        return "返回一条每日绿色低碳小贴士(示例插件)。"

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        return []

    def execute(self, **kwargs) -> ToolResult:
        start = time.time()
        return ToolResult(
            success=True,
            data={"text": "🌱 " + random.choice(TIPS), "source": "plugin:example_plugin"},
            execution_time=time.time() - start,
        )


def register(api) -> None:
    """插件入口:把工具注册进全局 ToolRegistry"""
    api.register_tool(DailyEcoTipTool(), category="eco", tags=["tip", "daily", "eco"])
