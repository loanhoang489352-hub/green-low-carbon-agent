"""
P12.1: 节能规划核心引擎

从家庭画像 + 城市政策生成可执行节能方案,严格无幻觉。
- 幻觉防火墙:节电数字必须可追溯到具体政策/电器参数
- 今日行动卡:固定 5 字段(目标/方案/提醒/时间/判定)
- 三级完成:全做/部分做/未做(streak 保留)
- 画像贯通:家庭画像跨模块共享
- 委托级别 0-3:决定是否自动执行(P12.2 已实装于 delegation.py)
"""
from .models import (
    HouseholdProfile,
    EnergyAction,
    EnergyPlan,
    TodayCard,
    CompletionLevel,
    PlanStatus,
)
from .policies import (
    CITY_TIER_PRICING,
    APPLIANCE_SAVINGS,
    WaterSavingStandard,
    GasSavingStandard,
    lookup_city_pricing,
    appliance_potential,
)
from .planner import EnergyPlanner
from .tracker import ActionTracker
# P12.2 delegation: level-based decisions
from .delegation import (
    DelegationLevel,
    DelegationDecision,
    LEVEL_LABELS,
    should_ask_confirmation,
    decide_for_write,
    get_delegation_level,
    set_delegation_level,
    parse_level_from_natural_language,
)

__all__ = [
    # Models (P12.1)
    "HouseholdProfile",
    "EnergyAction",
    "EnergyPlan",
    "TodayCard",
    "CompletionLevel",
    "PlanStatus",
    # Policies (P12.1)
    "CITY_TIER_PRICING",
    "APPLIANCE_SAVINGS",
    "WaterSavingStandard",
    "GasSavingStandard",
    "lookup_city_pricing",
    "appliance_potential",
    # Planner + Tracker (P12.1)
    "EnergyPlanner",
    "ActionTracker",
    # Delegation (P12.2)
    "DelegationLevel",
    "DelegationDecision",
    "LEVEL_LABELS",
    "should_ask_confirmation",
    "decide_for_write",
    "get_delegation_level",
    "set_delegation_level",
    "parse_level_from_natural_language",
]
