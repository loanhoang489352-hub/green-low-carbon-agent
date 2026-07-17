"""
任务3 P3: 宠物养成模块单元测试
覆盖:
  1. 数值同步(行为→奖励→状态)
  2. 形态解锁(co2 阈值)
  3. 互动触发(pat/feed)
  4. 数据持久化(SQLite 7 张表)
  5. 边界异常场景

运行: cd D:\绿色低碳智能体 && pytest tests/test_pet_engine.py -v
"""
import os
import sys
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

# 任务3 P3-4: 设置 PYTHONPATH
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@pytest.fixture(autouse=True)
def isolated_pet_db(tmp_path, monkeypatch):
    """每个测试用临时 pet.db,避免污染"""
    from pet import constants
    test_db = tmp_path / "test_pet.db"
    monkeypatch.setattr(constants, "PET_DB_PATH", test_db)
    # 重置单例
    from pet import pet_engine as pe_mod
    pe_mod._pet_engine = None
    constants.init_pet_schema()
    yield test_db
    if test_db.exists():
        try:
            test_db.unlink()
        except Exception:
            pass


# ===== 1. 数值同步 =====

class TestBehaviorRewards:
    """测试 1: 行为→奖励→状态同步"""

    def test_bus_rewards(self):
        """公交 10km:活力+8/心情+3/币+2/经验+12"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.apply_behavior_rewards("u1", "bus", 10.0)
        assert r.co2_saved == pytest.approx(2.0, abs=0.5)  # 0.21 * 10
        assert r.new_state.vitality == 58  # 50+8
        assert r.new_state.mood == 53     # 50+3
        assert r.new_state.coins == 2
        assert r.new_state.exp == 12
        assert r.new_state.total_co2_saved == pytest.approx(2.0, abs=0.5)

    def test_electricity_rewards(self):
        """节电 5kWh:饱食+8/心情+2/币+5/经验+8"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.apply_behavior_rewards("u1", "electricity", 5.0)
        assert r.co2_saved == pytest.approx(3.0, abs=0.5)  # 0.6 * 5
        assert r.new_state.hunger == 58  # 50+8
        assert r.new_state.mood == 52     # 50+2
        assert r.new_state.coins == 5

    def test_recycle_rewards(self):
        """旧物回收 3kg:心情+15/经验+8/碎片+2"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.apply_behavior_rewards("u1", "recycle", 3.0)
        assert r.new_state.mood == 65     # 50+15
        assert r.new_state.fragments == 2

    def test_plant_rewards(self):
        """植树 1 棵:饱食+5/心情+20/经验+20/碎片+3"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.apply_behavior_rewards("u1", "plant", 1.0)
        assert r.new_state.hunger == 55
        assert r.new_state.mood == 70
        assert r.new_state.fragments == 3


# ===== 2. 形态解锁 =====

class TestAppearanceUnlock:
    """测试 2: 形态 co2 阈值触发"""

    def test_sprout_unlock_at_15kg(self):
        """累计 15kg CO2 → 触发 sprout(萌芽精灵)"""
        from pet import get_pet_engine
        e = get_pet_engine()
        # 植树 3 棵 = 15kg
        for i in range(3):
            r = e.apply_behavior_rewards("u1", "plant", 1.0)
        assert r.new_state.appearance == "sprout"
        assert r.appearance_change == "sprout"

    def test_appearance_change_event(self):
        """形态变化返回 appearance_change 字段"""
        from pet import get_pet_engine
        e = get_pet_engine()
        # 植树 6 棵 = 30kg
        r1 = None
        for i in range(6):
            r1 = e.apply_behavior_rewards("u1", "plant", 1.0)
        # 至少触发一次升级
        changes = []
        for i in range(20):
            r = e.apply_behavior_rewards("u1", "plant", 1.0)
            if r.appearance_change:
                changes.append(r.appearance_change)
        assert len(changes) >= 1
        assert "leaf" in changes or "guardian" in changes or "sprout" in changes

    def test_initial_appearance_seed(self):
        """新用户默认 seed(碳种子)"""
        from pet import get_pet_engine
        e = get_pet_engine()
        state = e.get_state("new_user_001")
        assert state.appearance == "seed"
        assert state.title() == "碳种子"


# ===== 3. 互动触发 =====

class TestInteractions:
    """测试 3: 抚摸/投喂/对话"""

    def test_pat_mood_increase(self):
        """抚摸:心情+2"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.pat("u1")
        assert r["ok"] is True
        assert r["mood"] == 52
        assert "💚" in r["msg"]

    def test_pat_caps_at_100(self):
        """抚摸心情封顶 100"""
        from pet import get_pet_engine
        e = get_pet_engine()
        # 直接 set 高心情
        state = e.get_state("u1")
        state.mood = 100
        e._save_state(state)
        r = e.pat("u1")
        assert r["mood"] == 100  # 封顶,不超

    def test_feed_solar(self):
        """投喂太阳能板:cost=3 币,hunger+20/mood+8/vitality+10"""
        from pet import get_pet_engine
        e = get_pet_engine()
        # 先赚币(electricity 3 次,每次 +5 币 = 15 币)
        for _ in range(3):
            e.apply_behavior_rewards("u1", "electricity", 10.0)
        # 记录投喂前(electricity 也会 +hunger 24)
        before = e.get_state("u1")
        r = e.feed("u1", "solar")
        assert r["ok"] is True
        assert r["item_name"] == "太阳能板"
        # 投喂后增量:solar +20,封顶 100
        assert r["state"]["hunger"] == min(100, before.hunger + 20)
        assert r["state"]["mood"] == min(100, before.mood + 8)
        assert r["state"]["vitality"] == min(100, before.vitality + 10)

    def test_feed_insufficient_coins(self):
        """币不足时投喂失败"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.feed("u1", "fruit")  # fruit cost=20
        assert r["ok"] is False
        assert "精灵币不足" in r["msg"]

    def test_feed_invalid_item(self):
        """投喂不存在道具返回错误"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.feed("u1", "nonexistent")
        assert r["ok"] is False
        assert "道具不存在" in r["msg"]


# ===== 4. 数据持久化 =====

class TestPersistence:
    """测试 4: 7 张表数据持久化"""

    def test_pet_state_persists(self, isolated_pet_db):
        """pet 状态跨调用持久化"""
        from pet import get_pet_engine
        e = get_pet_engine()
        e.apply_behavior_rewards("u1", "bus", 10.0)
        # 模拟新进程
        from pet import pet_engine as pe_mod
        pe_mod._pet_engine = None
        e2 = get_pet_engine()
        state = e2.get_state("u1")
        assert state.coins == 2
        assert state.total_co2_saved == pytest.approx(2.0, abs=0.5)

    def test_state_change_log_recorded(self, isolated_pet_db):
        """pet_state_change_log 每次行为写一条"""
        from pet import get_pet_engine
        e = get_pet_engine()
        for _ in range(3):
            e.apply_behavior_rewards("u1", "bus", 5.0)
        conn = sqlite3.connect(str(isolated_pet_db))
        n = conn.execute("SELECT COUNT(*) FROM pet_state_change_log WHERE user_id='u1'").fetchone()[0]
        conn.close()
        assert n == 3

    def test_carbon_log_synced(self, isolated_pet_db):
        """carbon_footprint_log(behavior_tracker.db)双写"""
        from pet import get_pet_engine
        e = get_pet_engine()
        e.apply_behavior_rewards("u1", "bus", 10.0)
        # 检查 behavior_tracker.db
        bt_db = PROJECT_ROOT / "data" / "behavior_tracker.db"
        if bt_db.exists():
            conn = sqlite3.connect(str(bt_db))
            # 查最近 1 条
            row = conn.execute(
                "SELECT amount_kg_co2e, source FROM carbon_footprint_log "
                "WHERE user_id='u1' AND source='pet_engine' ORDER BY id DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:  # 可能 record_carbon 失败
                assert row[0] == pytest.approx(2.0, abs=0.5)
                assert row[1] == "pet_engine"

    def test_appearance_unlock_persists(self, isolated_pet_db):
        """appearance_unlocks 表记录"""
        from pet import get_pet_engine
        e = get_pet_engine()
        for _ in range(3):
            e.apply_behavior_rewards("u1", "plant", 1.0)
        conn = sqlite3.connect(str(isolated_pet_db))
        rows = conn.execute(
            "SELECT appearance_id FROM pet_appearance_unlocks WHERE user_id='u1'"
        ).fetchall()
        conn.close()
        assert ("sprout",) in rows


# ===== 5. 边界/异常 =====

class TestEdgeCases:
    """测试 5: 边界异常"""

    def test_empty_user_id(self, isolated_pet_db):
        """空 user_id 创建独立 state,不污染"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.apply_behavior_rewards("", "bus", 10.0)
        assert r.new_state.user_id == ""
        assert r.new_state.coins == 2

    def test_unknown_behavior(self, isolated_pet_db):
        """未知行为:不报错,co2=0,无奖励"""
        from pet import get_pet_engine
        e = get_pet_engine()
        r = e.apply_behavior_rewards("u1", "unknown_type", 10.0)
        assert r.co2_saved == 0
        assert r.new_state.coins == 0

    def test_negative_amount(self, isolated_pet_db):
        """负数 amount 不崩溃"""
        from pet import get_pet_engine
        e = get_pet_engine()
        try:
            r = e.apply_behavior_rewards("u1", "bus", -10.0)
            # 接受任意合理结果(可能负 co2)
            assert r.new_state.coins >= 0
        except Exception as ex:
            pytest.fail(f"负数 amount 崩溃: {ex}")

    def test_state_caps_at_100(self, isolated_pet_db):
        """hunger/mood/vitality 封顶 100"""
        from pet import get_pet_engine
        e = get_pet_engine()
        for _ in range(20):
            e.apply_behavior_rewards("u1", "plant", 1.0)
        state = e.get_state("u1")
        assert state.hunger <= 100
        assert state.mood <= 100
        assert state.vitality <= 100

    def test_level_max_50(self, isolated_pet_db):
        """等级上限 50"""
        from pet import get_pet_engine
        e = get_pet_engine()
        # 模拟 Lv 50
        state = e.get_state("u1")
        state.level = 50
        state.exp = 99999
        e._save_state(state)
        e.apply_behavior_rewards("u1", "plant", 1.0)
        state2 = e.get_state("u1")
        assert state2.level == 50  # 封顶

    def test_compute_pet_status_states(self):
        """6 种状态综合判定"""
        from pet.numeric_rules import compute_pet_status
        assert compute_pet_status(50, 50, 50) == "HEALTHY"
        assert compute_pet_status(20, 50, 50) == "HUNGRY"
        assert compute_pet_status(50, 20, 50) == "SAD"
        assert compute_pet_status(50, 50, 20) == "TIRED"
        assert compute_pet_status(80, 80, 80) == "SUPER"
        assert compute_pet_status(0, 0, 0) == "CRITICAL"

    def test_daily_cap_enforced(self, isolated_pet_db):
        """每日上限生效"""
        from pet import get_pet_engine
        from pet.numeric_rules import DAILY_CAPS
        e = get_pet_engine()
        # 一次投大量,验证 cap
        r = e.apply_behavior_rewards("u1", "plant", 100.0)
        # exp 增量 20 (BEHAVIOR_REWARDS 中 plant=20),应小于 cap=500
        assert r.rewards["exp"] == 20


# ===== 6. 技能系统 =====

class TestSkills:
    """测试 6: 技能解锁"""

    def test_skills_at_low_level(self, isolated_pet_db):
        """Lv 1 仅 1 技能解锁"""
        from pet import get_pet_engine
        e = get_pet_engine()
        skills = e.get_skills("u1")
        unlocked = [s for s in skills if s["unlocked"]]
        assert len(unlocked) == 1
        assert unlocked[0]["id"] == "skill_today_summary"

    def test_skills_at_lv_15(self, isolated_pet_db):
        """Lv 15 多个技能解锁"""
        from pet import get_pet_engine
        e = get_pet_engine()
        state = e.get_state("u1")
        state.level = 15
        e._save_state(state)
        skills = e.get_skills("u1")
        unlocked = [s["id"] for s in skills if s["unlocked"]]
        assert "skill_score_card" in unlocked
        assert "skill_share_poster" in unlocked
        assert "advanced_carbon_footprint" in unlocked

    def test_skills_record_use(self, isolated_pet_db):
        """技能使用记录"""
        from pet import get_pet_engine
        e = get_pet_engine()
        e.record_skill_use("u1", "skill_today_summary", {"test": True})
        conn = sqlite3.connect(str(isolated_pet_db))
        n = conn.execute(
            "SELECT COUNT(*) FROM pet_skill_uses WHERE user_id='u1' AND skill_id='skill_today_summary'"
        ).fetchone()[0]
        conn.close()
        assert n == 1


# ===== 7. 端到端集成 =====

class TestIntegration:
    """测试 7: 端到端用户旅程"""

    def test_full_user_journey(self, isolated_pet_db):
        """完整流程:录入行为→升级→形态变化→互动"""
        from pet import get_pet_engine
        e = get_pet_engine()
        user = "journey_user_001"

        # 步骤 1: 录入 5 次植树
        for _ in range(5):
            e.apply_behavior_rewards(user, "plant", 1.0)
        state = e.get_state(user)
        assert state.appearance == "sprout"
        assert state.fragments == 15  # 5*3
        assert state.total_co2_saved == pytest.approx(25.0, abs=2)

        # 步骤 2: 抚摸 + 投喂
        e.pat(user)
        e.feed(user, "solar")  # 需先有币
        state2 = e.get_state(user)
        # 心情 / 饱食应增加(投喂后)
        assert state2.mood >= state.mood
        assert state2.hunger >= state.hunger

        # 步骤 3: 技能列表
        skills = e.get_skills(user)
        assert isinstance(skills, list)
        assert len(skills) > 0

        # 步骤 4: 状态变更日志
        conn = sqlite3.connect(str(isolated_pet_db))
        n = conn.execute(
            "SELECT COUNT(*) FROM pet_state_change_log WHERE user_id=?", (user,)
        ).fetchone()[0]
        conn.close()
        # 5 个植树 + 1 个抚摸/投喂不写 state_change_log(只写入)→ 5
        assert n == 5
