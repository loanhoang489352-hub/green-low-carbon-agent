"""
任务2 + 任务6: 数值规则 - 行为→资源映射,等级曲线,每日上限,形态阈值
集中常量便于调整,无副作用。
"""

from __future__ import annotations

from typing import Dict


# 任务2: 行为→资源映射
# 字段:hunger/mood/vitality/coins/exp/fragments (增量)
BEHAVIOR_REWARDS: Dict[str, Dict[str, int]] = {
    "bus": {"hunger": 0, "mood": 3, "vitality": 8, "coins": 2, "exp": 12, "fragments": 0},
    "walk": {"hunger": 0, "mood": 2, "vitality": 6, "coins": 1, "exp": 10, "fragments": 0},
    "bike": {"hunger": 0, "mood": 3, "vitality": 8, "coins": 2, "exp": 12, "fragments": 0},
    "electricity": {"hunger": 8, "mood": 2, "vitality": 0, "coins": 5, "exp": 8, "fragments": 0},
    "water": {"hunger": 6, "mood": 1, "vitality": 0, "coins": 3, "exp": 6, "fragments": 0},
    "recycle_sort": {"hunger": 4, "mood": 4, "vitality": 0, "coins": 2, "exp": 6, "fragments": 0},
    "plastic": {"hunger": 2, "mood": 10, "vitality": 0, "coins": 0, "exp": 5, "fragments": 1},
    "recycle": {"hunger": 0, "mood": 15, "vitality": 0, "coins": 0, "exp": 8, "fragments": 2},
    "purchase": {"hunger": 0, "mood": 5, "vitality": 0, "coins": 0, "exp": 8, "fragments": 0},
    "plant": {"hunger": 5, "mood": 20, "vitality": 0, "coins": 0, "exp": 20, "fragments": 3},
}


# 任务2: 每日上限(防沉迷 + 防通胀)
DAILY_CAPS = {
    "exp": 500,
    "coins": 200,
    "fragments": 10,
    "hunger_delta": 30,
    "mood_delta": 30,
    "vitality_delta": 30,
}


# 任务2: 状态衰减
DECAY_DAILY = {"hunger": 5, "mood": 3, "vitality": 4}


# 任务2: 升级曲线 exp_to_next(L) = 100 * (L^1.6)
def exp_to_next_level(level: int) -> int:
    if level >= 50:
        return 0
    return int(100 * (level**1.6))


# 任务4: 形态阈值(累计 kg CO2,单约束 — 等级是"努力程度"指示,不作为门槛)
# 任务6 修复: 降低门槛让小积累也能触发(原双约束对单植树测试过严)
APPEARANCE_TIERS = [
    {"id": "mythic", "co2_min": 1500, "title": "环保传奇"},
    {"id": "legend", "co2_min": 600, "title": "碳中和圣灵"},
    {"id": "guardian", "co2_min": 150, "title": "守护者"},
    {"id": "leaf", "co2_min": 50, "title": "绿叶使者"},
    {"id": "sprout", "co2_min": 15, "title": "萌芽精灵"},
    {"id": "seed", "co2_min": 0, "title": "碳种子"},
]


# 任务4: 栖息地阈值
HABITAT_UNLOCKS = [
    {"id": "carbon_neutral", "co2_min": 1000, "consec_days_min": 100, "name": "碳中和家园"},
    {"id": "forest_camp", "co2_min": 400, "consec_days_min": 30, "name": "森林营地"},
    {"id": "solar_house", "co2_min": 150, "consec_days_min": 7, "name": "光伏小屋"},
    {"id": "green_house", "co2_min": 0, "consec_days_min": 0, "name": "绿植小屋"},
]


# 任务4: 图鉴阈值
CODEX_THRESHOLDS = {
    "codex_bus": 10,
    "codex_bike": 10,
    "codex_walk": 10,
    "codex_electricity": 100,
    "codex_water": 10,
    "codex_recycle": 50,
    "codex_plastic": 100,
    "codex_plant": 5,
    "codex_purchase": 1000,
}
BEHAVIOR_TO_CODEX = {
    "bus": "codex_bus",
    "bike": "codex_bike",
    "walk": "codex_walk",
    "electricity": "codex_electricity",
    "water": "codex_water",
    "recycle": "codex_recycle",
    "plastic": "codex_plastic",
    "plant": "codex_plant",
    "purchase": "codex_purchase",
}


# 任务4: 成就定义
ACHIEVEMENTS = {
    "achv_7day_travel": {
        "name": "连续7天低碳出行",
        "cond": "consecutive_days>=7",
        "reward": "环保眼镜",
    },
    "achv_30day_electricity": {
        "name": "月度节电达标",
        "cond": "monthly_electricity>=50",
        "reward": "节能徽章",
    },
    "achv_yearly_carbon": {
        "name": "年度碳减排达标",
        "cond": "yearly_carbon>=500",
        "reward": "胜利舞蹈",
    },
    "achv_first_plant": {"name": "首次植树", "cond": "plant>=1", "reward": "小树苗头饰"},
    "achv_100_recycle": {"name": "回收百次", "cond": "recycle>=100", "reward": "回收招手"},
    "achv_carbon_saver_100": {
        "name": "减碳百公斤",
        "cond": "total_co2>=100",
        "reward": "形态提前解锁",
    },
    "achv_carbon_saver_1000": {
        "name": "减碳千公斤",
        "cond": "total_co2>=1000",
        "reward": "圣灵光环",
    },
    "achv_streak_30": {
        "name": "连续30天打卡",
        "cond": "consecutive_days>=30",
        "reward": "森林营地优先",
    },
    "achv_streak_100": {
        "name": "连续100天打卡",
        "cond": "consecutive_days>=100",
        "reward": "环保传奇优先",
    },
    "achv_pet_max_level": {"name": "精灵满级", "cond": "level==50", "reward": "升天动画"},
    "achv_all_codex": {"name": "集齐图鉴", "cond": "codex_count==9", "reward": "低碳大师称号"},
}


# 任务5: 技能解锁等级
SKILL_UNLOCK = {
    "skill_today_summary": 1,
    "skill_lifetime_impact": 5,
    "skill_score_card": 10,
    "skill_share_poster": 15,
    "advanced_carbon_footprint": 15,
    "advanced_personalized_advice": 25,
    "advanced_compare_peers": 30,
}


# 任务3: 状态综合判定
def compute_pet_status(hunger: int, mood: int, vitality: int) -> str:
    if hunger == 0 and mood == 0 and vitality == 0:
        return "CRITICAL"
    if hunger < 30:
        return "HUNGRY"
    if mood < 30:
        return "SAD"
    if vitality < 30:
        return "TIRED"
    if hunger >= 80 and mood >= 80 and vitality >= 80:
        return "SUPER"
    return "HEALTHY"
