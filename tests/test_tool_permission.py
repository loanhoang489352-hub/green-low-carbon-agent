"""P16: 工具级权限门单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.confirmation import ActionRisk
from agent.tool_permission import (
    PermissionDecision,
    tool_risk,
    decide,
    check_tool_permission,
)


class _Tool:
    def __init__(self, name="query", risk=None, description=""):
        self.name = name
        self.risk = risk
        self.description = description


def test_tool_risk_reads_declared():
    assert tool_risk(_Tool(risk="high")) == ActionRisk.HIGH
    assert tool_risk(_Tool(risk="medium")) == ActionRisk.MEDIUM
    assert tool_risk(_Tool(risk="low")) == ActionRisk.LOW


def test_tool_risk_falls_back_to_name_heuristic():
    # 未声明 risk → 按 name 启发式
    assert tool_risk(_Tool(name="payment_tool")) == ActionRisk.HIGH
    assert tool_risk(_Tool(name="activate_plan")) == ActionRisk.MEDIUM
    assert tool_risk(_Tool(name="weather_query")) == ActionRisk.LOW


def test_decide_defaults_allow():
    assert decide(_Tool(risk="low")) == PermissionDecision.ALLOW
    assert decide(_Tool(risk="medium")) == PermissionDecision.ALLOW
    assert decide(_Tool(risk="high")) == PermissionDecision.CONFIRM


def test_check_tool_permission_blocks_high_risk():
    assert check_tool_permission(_Tool(risk="low")) is None
    assert check_tool_permission(_Tool(risk="high")) is not None
    assert "确认" in check_tool_permission(_Tool(risk="high"))


def test_default_base_tool_risk_is_low():
    # BaseTool 默认 risk="low" → 现有工具不触发确认门
    from agent.tools.base import BaseTool

    class DummyTool(BaseTool):
        @property
        def name(self):
            return "dummy"

        @property
        def description(self):
            return "dummy tool"

        @property
        def parameters(self):
            return []

        def execute(self, **kw):
            from agent.tools.base import ToolResult
            return ToolResult(success=True)

    assert DummyTool().risk == "low"
    assert check_tool_permission(DummyTool()) is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {name} PASSED")
    print("\n🎉 All tool permission tests PASSED")
