"""P16: Human-in-the-loop 确认流单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agent.confirmation import (
    ActionRisk,
    risk_for_action,
    requires_confirmation,
    ConfirmationStore,
    get_confirmation_store,
)


def test_risk_for_action_mapping():
    assert risk_for_action("payment") == ActionRisk.HIGH
    assert risk_for_action("irreversible_delete") == ActionRisk.HIGH
    assert risk_for_action("activate_plan") == ActionRisk.MEDIUM
    assert risk_for_action("complete_action") == ActionRisk.MEDIUM
    assert risk_for_action("knowledge_query") == ActionRisk.LOW
    assert risk_for_action("闲聊") == ActionRisk.LOW


def test_requires_confirmation_by_risk_and_delegation():
    # HIGH 永远确认
    assert requires_confirmation(ActionRisk.HIGH, delegation_level=3) is True
    # MEDIUM 在 delegation < 3 确认,3 全权委托不确认
    assert requires_confirmation(ActionRisk.MEDIUM, delegation_level=1) is True
    assert requires_confirmation(ActionRisk.MEDIUM, delegation_level=3) is False
    # LOW 永不确认
    assert requires_confirmation(ActionRisk.LOW, delegation_level=0) is False


def test_confirmation_store_lifecycle():
    s = ConfirmationStore()
    c = s.add("alice", "activate_plan", "激活节能方案", ActionRisk.MEDIUM)
    assert c.status == "pending"
    assert s.get(c.id) is not None
    assert len(s.list_pending("alice")) == 1
    # 他人不可见
    assert s.list_pending("bob") == []
    # approve
    assert s.approve(c.id) is True
    assert s.get(c.id).status == "approved"
    assert s.list_pending("alice") == []
    # 重复 approve/reject 无效
    assert s.reject(c.id) is False


def test_confirmation_store_reject():
    s = ConfirmationStore()
    c = s.add("alice", "purchase", "购买设备", ActionRisk.HIGH)
    assert s.reject(c.id) is True
    assert s.get(c.id).status == "rejected"


def test_confirmation_store_cleanup_expired():
    from datetime import datetime, timedelta
    s = ConfirmationStore()
    c = s.add("alice", "activate_plan", "旧确认", ActionRisk.MEDIUM)
    # 手动把时间拨到 25 小时前
    c.created_at = (datetime.now() - timedelta(hours=25)).isoformat()
    assert s.cleanup_expired() == 1
    assert s.get(c.id) is None


def test_get_confirmation_store_singleton():
    s1 = get_confirmation_store()
    s2 = get_confirmation_store()
    assert s1 is s2
    s1.reset()


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✅ {name} PASSED")
    print("\n🎉 All confirmation tests PASSED")
