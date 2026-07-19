"""
P12.1: 节能规划数据模型

所有 dataclass 字段都用最朴素的类型,便于跨模块(JSON/SQLite/Agent)穿透。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import List, Optional


class CompletionLevel(str, Enum):
    """三级完成:全做/部分做/未做 (P12.1 PPT 设计)
    partial 也算 streak(从交小燃学)
    """
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"

    @classmethod
    def counts_as_streak(cls, level: str) -> bool:
        """只有 none 不算 streak,full / partial 都算"""
        return level != cls.NONE.value


class PlanStatus(str, Enum):
    """方案状态"""
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class HouseholdProfile:
    """家庭画像 — 跨模块共享

    fields:
      user_id                 : 用户 ID
      family_size             : 家庭人数(影响用电规模)
      home_size_sqm           : 住房面积 (m²)
      city                    : 用于查阶梯电价
      monthly_electricity_bill: 月电费(元)
      monthly_water_bill      : 月水费(元)
      monthly_gas_bill        : 月燃气费(元)
      appliances              : 家中主要电器(关键词列表,如 ["空调", "热水器"])
      peak_offpeak_usage      : "peak"|"offpeak"|"mixed"
      ac_temp_setting         : 空调设定温度(℃)
      delegation_level        : 0/1/2/3
      created_at              : 首次建模时间
      updated_at              : 最近更新时间
    """
    user_id: str
    family_size: int = 3
    home_size_sqm: float = 90.0
    city: str = "beijing"
    monthly_electricity_bill: float = 200.0
    monthly_water_bill: float = 60.0
    monthly_gas_bill: float = 80.0
    appliances: List[str] = field(default_factory=lambda: ["空调", "热水器", "冰箱", "洗衣机"])
    peak_offpeak_usage: str = "mixed"
    ac_temp_setting: int = 24
    delegation_level: int = 1
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HouseholdProfile":
        # 过滤多余字段,容错 None / missing keys
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class EnergyAction:
    """一个具体节能行动

    每个 action 必须有 source_ref (幻觉防火墙要求!)
    """
    id: str
    category: str                                # "water"|"electricity"|"gas"
    title: str                                   # 用户能看懂的标题
    description: str                             # 具体怎么做
    estimated_saving_kwh: float                  # 节省电量 (kWh/动作单位)
    estimated_saving_cny: float                  # 节省钱 (元/动作单位)
    estimated_saving_co2_kg: float               # 减排 CO2 (kg)
    difficulty: int                              # 1=易 2=中 3=难
    when_to_do: str                              # "今天晚上"|"周末"|"随时"
    source_ref: str                              # 数据来源:policy:<文件>|appliance:<名称>|standard:<来源>

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EnergyPlan:
    """整张节能方案 = 画像快照 + 一组行动 + 总节省

    blocked / warning: 守卫(guard)失败的标记;blocked=True 时 actions=[],
    warning 形如 "GUARD_XXX: <原因>"。
    """
    id: str
    user_id: str
    profile_snapshot: HouseholdProfile
    actions: List[EnergyAction]
    total_estimated_saving_cny: float
    total_estimated_saving_co2_kg: float
    created_at: str
    status: str  # "draft"|"active"|"completed"|"blocked"
    warning: Optional[str] = None
    blocked: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "profile_snapshot": self.profile_snapshot.to_dict(),
            "actions": [a.to_dict() for a in self.actions],
            "total_estimated_saving_cny": self.total_estimated_saving_cny,
            "total_estimated_saving_co2_kg": self.total_estimated_saving_co2_kg,
            "created_at": self.created_at,
            "status": self.status,
            "warning": self.warning,
            "blocked": self.blocked,
        }


@dataclass
class TodayCard:
    """今日行动卡 — PPT 设计的固定 5 字段

      目标    : 今天要省多少 / 减多少
      方案    : 具体哪 3 件事(从 plan 抽)
      提醒    : 安全/风险提示
      时间    : 何时做
      判定    : 用户反馈后怎么算完成度
    """
    user_id: str
    plan_id: str
    goal: str                    # "今日省 X 元 / Y kg CO2"
    actions: List[EnergyAction]  # 抽 3 个最易执行的
    reminder: str                # "夜间用电避开 18-21 时高峰"
    when_to_do: str              # "今天 21:00 前完成"
    judge: str                   # "点击反馈:全做/部分做/未做"

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "plan_id": self.plan_id,
            "goal": self.goal,
            "actions": [a.to_dict() for a in self.actions],
            "reminder": self.reminder,
            "when_to_do": self.when_to_do,
            "judge": self.judge,
        }
