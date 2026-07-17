"""
M1-T1: 多品种低碳主题宠物
5 大生态系(绿植/光伏/水循环/固废/低碳出行)+ 抽取/图鉴/收集成就
低耦合:新增数据表 + SpeciesRegistry,不动原 pets 表结构
"""
from __future__ import annotations

import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from pathlib import Path

from .constants import _get_conn, init_pet_schema

_logger = logging.getLogger("pet.species")


# 5 大生态系
SPECIES_LIBRARY: Dict[str, Dict[str, Any]] = {
    "greenleaf": {
        "name": "绿叶精灵·芽",
        "family": "绿植系",
        "rarity": "common",
        "boost_category": "electricity",      # 被动加成:节电类 +20%
        "evolutions": [
            {"lv": 1, "name": "绿叶精灵·芽", "asset": "greenleaf_lv1"},
            {"lv": 10, "name": "绿叶精灵·苗", "asset": "greenleaf_lv2"},
            {"lv": 25, "name": "绿叶精灵·树", "asset": "greenleaf_lv3"},
            {"lv": 50, "name": "绿叶精灵·森", "asset": "greenleaf_lv4"},
        ],
        "skill": "光伏节能 — 节电类行为额外 +20% 经验",
    },
    "suncore": {
        "name": "光伏核灵·芯",
        "family": "光伏能源系",
        "rarity": "rare",
        "boost_category": "electricity",
        "evolutions": [
            {"lv": 1, "name": "光伏核灵·芯", "asset": "suncore_lv1"},
            {"lv": 10, "name": "光伏核灵·板", "asset": "suncore_lv2"},
            {"lv": 25, "name": "光伏核灵·场", "asset": "suncore_lv3"},
            {"lv": 50, "name": "光伏核灵·星", "asset": "suncore_lv4"},
        ],
        "skill": "光伏增效 — 节电/出行类 +15% 精灵币",
    },
    "aquaflow": {
        "name": "水循环灵·滴",
        "family": "水循环系",
        "rarity": "common",
        "boost_category": "water",
        "evolutions": [
            {"lv": 1, "name": "水循环灵·滴", "asset": "aquaflow_lv1"},
            {"lv": 10, "name": "水循环灵·溪", "asset": "aquaflow_lv2"},
            {"lv": 25, "name": "水循环灵·河", "asset": "aquaflow_lv3"},
            {"lv": 50, "name": "水循环灵·海", "asset": "aquaflow_lv4"},
        ],
        "skill": "循环水效 — 节水类 +25% 心情",
    },
    "recyclon": {
        "name": "固废回收者·箱",
        "family": "固废回收系",
        "rarity": "rare",
        "boost_category": "recycle",
        "evolutions": [
            {"lv": 1, "name": "固废回收者·箱", "asset": "recyclon_lv1"},
            {"lv": 10, "name": "固废回收者·仓", "asset": "recyclon_lv2"},
            {"lv": 25, "name": "固废回收者·站", "asset": "recyclon_lv3"},
            {"lv": 50, "name": "固废回收者·星环", "asset": "recyclon_lv4"},
        ],
        "skill": "回收加成 — 回收/减塑类 +30% 碎片",
    },
    "transitling": {
        "name": "低碳出行者·行",
        "family": "低碳出行系",
        "rarity": "common",
        "boost_category": "bus",
        "evolutions": [
            {"lv": 1, "name": "低碳出行者·行", "asset": "transitling_lv1"},
            {"lv": 10, "name": "低碳出行者·轮", "asset": "transitling_lv2"},
            {"lv": 25, "name": "低碳出行者·翼", "asset": "transitling_lv3"},
            {"lv": 50, "name": "低碳出行者·星轨", "asset": "transitling_lv4"},
        ],
        "skill": "出行加速 — 公交/骑行/步行 +30% 活力",
    },
}

# 抽卡池权重(按稀有度)
SPECIES_GACHA_WEIGHTS = {
    "common": 60,
    "rare": 25,
    "epic": 12,
    "legendary": 3,
}

# 抽卡所需精灵币
GACHA_COST_SINGLE = 50
GACHA_COST_TEN = 450  # 10 连优惠

# 数据表初始化(追加 3 张表,不改原 7 张)
def init_species_schema() -> None:
    """M1-T1: 扩展 3 张表(不动原 7 张)"""
    conn = _get_conn()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_pets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            species_id TEXT,
            nickname TEXT,
            level INTEGER DEFAULT 1,
            exp INTEGER DEFAULT 0,
            active BOOLEAN DEFAULT FALSE,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (user_id, species_id, nickname)
        );

        CREATE TABLE IF NOT EXISTS user_codex_species (
            user_id TEXT,
            species_id TEXT,
            unlocked_at TEXT,
            PRIMARY KEY (user_id, species_id)
        );

        CREATE TABLE IF NOT EXISTS species_collection_achievements (
            user_id TEXT,
            family TEXT,
            count INTEGER,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, family)
        );
        """)
        conn.commit()
    finally:
        conn.close()


init_species_schema()


@dataclass
class PetInstance:
    """用户拥有的具体宠物实例"""
    id: int
    user_id: str
    species_id: str
    nickname: str
    level: int = 1
    exp: int = 0
    active: bool = False

    def species_data(self) -> Dict[str, Any]:
        return SPECIES_LIBRARY.get(self.species_id, {})

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["species_data"] = self.species_data()
        return d


class SpeciesRegistry:
    """M1-T1: 多品种宠物注册中心"""

    def __init__(self):
        self._conn = _get_conn()

    # ===== 抽卡 =====

    def gacha(self, user_id: str, n: int = 1) -> List[PetInstance]:
        """抽卡 1 次或 10 连

        Returns: 抽到的 PetInstance 列表
        """
        # 扣币
        cost = GACHA_COST_SINGLE if n == 1 else GACHA_COST_TEN
        try:
            from .pet_engine import get_pet_engine
            pe = get_pet_engine()
            state = pe.get_state(user_id)
            if state.coins < cost:
                return []  # 币不足
            state.coins -= cost
            pe._save_state(state)
        except Exception as e:
            _logger.debug("[species] 扣币失败: %s", e)
            return []

        # 抽取
        results = []
        species_list = list(SPECIES_LIBRARY.keys())
        for _ in range(n):
            sid = random.choice(species_list)
            # 加唯一昵称
            nickname = f"{SPECIES_LIBRARY[sid]['name']}-{int(time.time()) % 10000}"
            pet = self._create_pet(user_id, sid, nickname)
            results.append(pet)
        return results

    def _create_pet(self, user_id: str, species_id: str, nickname: str) -> PetInstance:
        cur = self._conn.execute(
            "INSERT INTO user_pets (user_id, species_id, nickname) VALUES (?, ?, ?)",
            (user_id, species_id, nickname)
        )
        self._conn.commit()
        pet_id = cur.lastrowid
        # 点亮图鉴
        self._conn.execute(
            "INSERT OR IGNORE INTO user_codex_species (user_id, species_id, unlocked_at) VALUES (?, ?, ?)",
            (user_id, species_id, time.strftime("%Y-%m-%d %H:%M:%S"))
        )
        self._conn.commit()
        # 家族收集成就
        family = SPECIES_LIBRARY.get(species_id, {}).get("family", "")
        if family:
            self._check_family_achievement(user_id, family)
        return PetInstance(
            id=pet_id, user_id=user_id, species_id=species_id,
            nickname=nickname, level=1, exp=0, active=False
        )

    def _check_family_achievement(self, user_id: str, family: str) -> None:
        # 统计该用户该家族收集数量
        cur = self._conn.execute(
            "SELECT COUNT(DISTINCT species_id) FROM user_pets WHERE user_id=?",
            (user_id,)
        )
        cnt = cur.fetchone()[0]
        self._conn.execute(
            "INSERT OR REPLACE INTO species_collection_achievements (user_id, family, count) VALUES (?, ?, ?)",
            (user_id, family, cnt)
        )
        self._conn.commit()

    # ===== 查询 =====

    def list_user_pets(self, user_id: str) -> List[PetInstance]:
        cur = self._conn.execute(
            "SELECT id, user_id, species_id, nickname, level, exp, active "
            "FROM user_pets WHERE user_id=? ORDER BY level DESC",
            (user_id,)
        )
        return [PetInstance(*row) for row in cur.fetchall()]

    def list_user_codex(self, user_id: str) -> List[Dict[str, Any]]:
        """用户图鉴(已解锁的 species)"""
        cur = self._conn.execute(
            "SELECT species_id, unlocked_at FROM user_codex_species WHERE user_id=?",
            (user_id,)
        )
        rows = cur.fetchall()
        return [
            {"species_id": sid, "unlocked_at": ts,
             "species_data": SPECIES_LIBRARY.get(sid, {})}
            for sid, ts in rows
        ]

    def set_active_pet(self, user_id: str, pet_id: int) -> bool:
        """切换出战宠物"""
        self._conn.execute("UPDATE user_pets SET active=FALSE WHERE user_id=?", (user_id,))
        cur = self._conn.execute(
            "UPDATE user_pets SET active=TRUE WHERE user_id=? AND id=?",
            (user_id, pet_id)
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get_active_pet(self, user_id: str) -> Optional[PetInstance]:
        cur = self._conn.execute(
            "SELECT id, user_id, species_id, nickname, level, exp, active "
            "FROM user_pets WHERE user_id=? AND active=TRUE LIMIT 1",
            (user_id,)
        )
        row = cur.fetchone()
        return PetInstance(*row) if row else None

    # ===== 收益加成 =====

    def apply_boost(self, user_id: str, behavior_type: str, base_rewards: Dict[str, int]) -> Dict[str, int]:
        """M1-T1: 对应系宠物的被动加成(累加到原 rewards)

        低耦合:不改 PetEngine.apply_behavior_rewards,只让 PetEngine 调用此方法
        """
        pet = self.get_active_pet(user_id)
        if not pet:
            return base_rewards
        sp = pet.species_data()
        if sp.get("boost_category") != behavior_type:
            return base_rewards
        # 加成 +20%(根据 rarity)
        rarity_boost = {"common": 1.10, "rare": 1.20, "epic": 1.30, "legendary": 1.50}.get(
            sp.get("rarity", "common"), 1.10
        )
        boosted = dict(base_rewards)
        for k in ("exp", "coins", "fragments", "mood", "vitality", "hunger"):
            if k in boosted:
                boosted[k] = int(boosted[k] * rarity_boost)
        return boosted


# 单例
_species_registry: Optional[SpeciesRegistry] = None


def get_species_registry() -> SpeciesRegistry:
    global _species_registry
    if _species_registry is None:
        _species_registry = SpeciesRegistry()
    return _species_registry
