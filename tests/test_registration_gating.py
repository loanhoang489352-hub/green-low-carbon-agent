"""P17: 上线/灰度注册管控单元测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _mgr():
    from auth.account_manager import AccountManager

    return AccountManager()


def test_register_closed_when_flag_false(monkeypatch):
    monkeypatch.setenv("REGISTRATION_OPEN", "false")
    monkeypatch.delenv("INVITE_CODE", raising=False)
    r = _mgr().register("user123", "password123")
    assert r["success"] is False
    assert "未开放" in r["error"]


def test_register_requires_invite_code(monkeypatch):
    monkeypatch.setenv("INVITE_CODE", "gray2026")
    monkeypatch.delenv("REGISTRATION_OPEN", raising=False)
    r = _mgr().register("user123", "password123")
    assert r["success"] is False
    assert "邀请码" in r["error"]


def test_register_wrong_invite_code(monkeypatch):
    monkeypatch.setenv("INVITE_CODE", "gray2026")
    r = _mgr().register("user123", "password123", "wrong-code")
    assert r["success"] is False
    assert "邀请码" in r["error"]


def test_register_open_by_default(monkeypatch):
    """未设任何环境变量 → 注册保持开放(向后兼容),且能走到用户名校验"""
    monkeypatch.delenv("REGISTRATION_OPEN", raising=False)
    monkeypatch.delenv("INVITE_CODE", raising=False)
    # 非法用户名 → 说明已通过 gating,进入格式校验(而非被 gating 拦截)
    r = _mgr().register("a", "password123")  # 用户名太短
    assert r["success"] is False
    assert "3-20" in r["error"]  # 命中用户名格式错误,而非"未开放/邀请码"


if __name__ == "__main__":
    import os
    os.environ["REGISTRATION_OPEN"] = "false"
    print(_mgr().register("user123", "pass123"))
    print("✅ registration gating tests PASSED")
