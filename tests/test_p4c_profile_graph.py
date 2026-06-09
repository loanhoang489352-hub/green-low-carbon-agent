"""
验证 P4-C: 用户画像图谱化
- C.1: UserProfileGraph to_dict / from_dict 完整
- C.2: UserProfileManager 同步到图谱(interests / stage / actions)
- C.3: behavior_events 持久化
- C.4: Goal / Achievement / CarbonFootprint 持久化
"""
import sys
import os
import gc
import tempfile
import sqlite3
import json
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _unique(prefix: str = "u") -> str:
    """每次调用生成唯一 user_id,避免测试间数据污染(Windows 文件锁场景)"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _reset_behavior_db():
    """删除 behavior_tracker.db 强制重建(P4-C 验证用)

    兜底:若删除失败(Windows 文件锁),改为 TRUNCATE 所有表。
    """
    db_path = Path("data/behavior_tracker.db")
    deleted = False
    for f in (db_path, db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-shm")):
        if f.exists():
            try:
                f.unlink()
                deleted = True
            except OSError:
                pass
    # 重置单例,让下次实例化时用新 db
    try:
        from user_profile import persistence as _p
        _p._persistence = None
    except ImportError:
        pass
    gc.collect()  # 释放 Python 侧的 sqlite3 Connection 引用
    # 兜底:文件删不掉时,清空所有表的内容(只影响本测试用户的数据)
    if not deleted and db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            for table in ("behavior_events", "user_goals",
                          "user_achievements", "carbon_footprint_log"):
                try:
                    conn.execute(f"DELETE FROM {table}")
                except sqlite3.OperationalError:
                    pass
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass


def test_profile_graph_serialization():
    """C.1: UserProfileGraph to_dict/from_dict 完整"""
    from user_profile.profile_graph import UserProfileGraph
    g = UserProfileGraph("u_ser")
    g.add_interest("low_carbon_travel", confidence=0.8)
    g.set_behavior_stage("行动")
    g.add_action("骑自行车", sentiment="positive", carbon_saved=2.5)

    data = g.to_dict()
    assert "nodes" in data and "edges" in data
    assert data["user_id"] == "u_ser"
    assert len(data["nodes"]) >= 4  # user + interest + stage + action
    print(f"   serialized: {len(data['nodes'])} nodes, {len(data['edges'])} edges")

    g2 = UserProfileGraph.from_dict(data)
    interests = [i[0] for i in g2.get_interests()]
    assert "low_carbon_travel" in interests
    assert g2.get_behavior_stage() == "行动"
    actions = g2.get_actions()
    assert "骑自行车" in actions
    print("✅ test_profile_graph_serialization PASSED")


def test_profile_manager_sync_to_graph():
    """C.2: UserProfileManager update_eco_profile 同步到图谱"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "up.db"
        from user_profile.user_profile import UserProfileManager
        from user_profile.profile_graph import UserProfileGraph
        upm = UserProfileManager(str(db))

        p = upm.get_profile("u_sync")
        assert "graph" in p, "profile 应有 graph 字段"
        print("   initial profile has graph field")

        upm.update_eco_profile("u_sync", {
            "primary_interests": ["low_carbon_travel", "waste_classification"],
            "behavior_stage": "行动",
        })
        p = upm.get_profile("u_sync")
        g = UserProfileGraph.from_dict(p["graph"])
        interests = [i[0] for i in g.get_interests()]
        assert "low_carbon_travel" in interests
        assert g.get_behavior_stage() == "行动"
        print(f"   after sync: interests={interests}, stage={g.get_behavior_stage()}")

        upm.update_eco_profile("u_sync", {
            "action_history": [
                {"action": "骑自行车", "carbon_saved": 2.5},
                {"action": "自带购物袋", "carbon_saved": 0.05},
            ],
        })
        p = upm.get_profile("u_sync")
        g = UserProfileGraph.from_dict(p["graph"])
        actions = g.get_actions()
        assert "骑自行车" in actions
        assert "自带购物袋" in actions
        print(f"   actions: {actions}")
    print("✅ test_profile_manager_sync_to_graph PASSED")


def test_profile_manager_backward_compat():
    """旧 profile 无 graph 字段时,get_profile 自动补全"""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "up_old.db"
        from user_profile.user_profile import UserProfileManager
        upm = UserProfileManager(str(db))

        # 直接 INSERT 旧格式数据(无 graph)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO user_profiles (user_id, profile_data, created_at, updated_at) "
            "VALUES (?, ?, ?, ?)",
            ("u_old", json.dumps({"user_id": "u_old", "basic_info": {}}, ensure_ascii=False),
             "2026-01-01", "2026-01-01"),
        )
        conn.commit()
        conn.close()

        p = upm.get_profile("u_old")
        assert "graph" in p, "旧 profile 也应有 graph 字段(兜底)"
        assert p["graph"]["user_id"] == "u_old"
    print("✅ test_profile_manager_backward_compat PASSED")


def test_behavior_events_persistence():
    """C.3: behavior_events 表含新字段且记录事件正常"""
    _reset_behavior_db()
    from db_schema import init_all_schemas
    init_all_schemas()

    from user_profile.persistence import get_behavior_persistence
    from user_profile import persistence as _pers_mod
    # 强制用新 db 路径(单例重置)
    _pers_mod._persistence = None
    pers = _pers_mod.BehaviorPersistence()
    uid = _unique("u_ev")

    ev_id = pers.record_event(
        user_id=uid,
        event_type="出行",
        event_data={"vehicle": "公交"},
        intent_type="action_report",
        carbon_impact=-1.5,
        related_interests=["low_carbon_travel"],
    )
    assert ev_id > 0

    events = pers.get_user_events(uid)
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "出行"
    assert e["carbon_impact"] == -1.5
    assert e["related_interests"] == ["low_carbon_travel"]
    print(f"   event: type={e['event_type']}, carbon_impact={e['carbon_impact']}")
    print("✅ test_behavior_events_persistence PASSED")


def test_goal_persistence():
    """C.4: user_goals 持久化 + 进度更新 + 自动完成"""
    _reset_behavior_db()
    from db_schema import init_all_schemas
    init_all_schemas()

    from user_profile import persistence as _pers_mod
    _pers_mod._persistence = None
    from user_profile.persistence import BehaviorPersistence
    pers = BehaviorPersistence()
    uid = _unique("u_g")

    gid = pers.create_goal(uid, "carbon_reduction", 5.0, deadline="2026-12-31")
    pers.update_goal_progress(gid, 3.0)
    active = pers.get_active_goals(uid)
    assert len(active) == 1
    assert active[0]["current_value"] == 3.0
    print(f"   goal {gid}: 3.0 / 5.0 active")

    # 完成
    pers.update_goal_progress(gid, 6.0)
    active = pers.get_active_goals(uid)
    assert len(active) == 0
    print(f"   goal {gid} auto-completed")
    print("✅ test_goal_persistence PASSED")


def test_achievement_persistence():
    """C.4: user_achievements 持久化 + UNIQUE 约束"""
    _reset_behavior_db()
    from db_schema import init_all_schemas
    init_all_schemas()

    from user_profile import persistence as _pers_mod
    _pers_mod._persistence = None
    from user_profile.persistence import BehaviorPersistence
    pers = BehaviorPersistence()
    uid = _unique("u_a")

    ok1 = pers.grant_achievement(uid, "first_ride", {"points": 10})
    ok2 = pers.grant_achievement(uid, "first_ride", {"points": 10})
    assert ok1 is True
    assert ok2 is False  # UNIQUE 冲突
    achs = pers.get_user_achievements(uid)
    assert len(achs) == 1
    print(f"   achievements: {[a['code'] for a in achs]}")
    print("✅ test_achievement_persistence PASSED")


def test_carbon_footprint_persistence():
    """C.4: carbon_footprint_log + weekly total"""
    _reset_behavior_db()
    from db_schema import init_all_schemas
    init_all_schemas()

    from user_profile import persistence as _pers_mod
    _pers_mod._persistence = None
    from user_profile.persistence import BehaviorPersistence
    pers = BehaviorPersistence()
    uid = _unique("u_c")

    pers.record_carbon(uid, "出行", 1.5, source="test")
    pers.record_carbon(uid, "用电", 2.0, source="test")
    total = pers.calculate_weekly_total(uid)
    assert total >= 3.5
    print(f"   weekly total: {total}kg CO2e")
    print("✅ test_carbon_footprint_persistence PASSED")


def test_behavior_tracker_uses_persistence():
    """BehaviorTracker._save_behavior 走 persistence 层"""
    _reset_behavior_db()
    from db_schema import init_all_schemas
    init_all_schemas()

    from user_profile import persistence as _pers_mod
    _pers_mod._persistence = None
    from user_profile.persistence import BehaviorPersistence
    from user_profile.behavior_tracker import BehaviorTracker

    pers = BehaviorPersistence()
    bt = BehaviorTracker()
    uid = _unique("u_bt")
    bt.record_travel(uid, "自行车", 3.0)
    # 注: record_diet / record_electricity 触发 AchievementSystem 中
    # 一个 _check_milestone 拼写错误的预存在 bug(非 P4-C 范围),
    # 此处仅验证 record_travel 路径

    events = pers.get_user_events(uid, limit=20)
    assert len(events) >= 1
    types = {e["event_type"] for e in events}
    assert "出行" in types
    print(f"   events: {len(events)} records, types={types}")
    print("✅ test_behavior_tracker_uses_persistence PASSED")


def test_profile_graph_exported():
    """C.2: UserProfileGraph 已在 user_profile 包导出"""
    from user_profile import UserProfileGraph, ProfileNode, ProfileEdge
    assert UserProfileGraph is not None
    assert ProfileNode is not None
    assert ProfileEdge is not None
    print("✅ test_profile_graph_exported PASSED")


if __name__ == "__main__":
    test_profile_graph_serialization()
    test_profile_manager_sync_to_graph()
    test_profile_manager_backward_compat()
    test_behavior_events_persistence()
    test_goal_persistence()
    test_achievement_persistence()
    test_carbon_footprint_persistence()
    test_behavior_tracker_uses_persistence()
    test_profile_graph_exported()
    print("\n🎉 all P4-C profile graph tests passed")
