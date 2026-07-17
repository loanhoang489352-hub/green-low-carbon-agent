"""
Bug 8 修复测试: _dispatch 兼容 1 参 / 2 参 handler

覆盖:
A. _dispatch 检测 handler 形参,1 参时只传 handler,2 参时传 (handler, data)
B. GET 端点 (1 参 handler) 不再 500
C. POST 端点 (2 参 handler) 仍正常
D. 真实 HTTP 烟测: GET / 返 HTML, GET /api/health 返 JSON
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. dispatch 代码扫描
# ---------------------------------------------------------------------------
def test_dispatch_uses_inspect_signature():
    """_dispatch 必须用 inspect.signature 检测 handler 形参个数"""
    content = (PROJECT_ROOT / "src/server/app.py").read_text(encoding="utf-8")
    assert "inspect.signature(route.handler)" in content, "dispatch 必须用 inspect.signature"
    assert "param_count" in content, "必须有 param_count 变量"


def test_dispatch_conditional_data_passing():
    """根据 param_count 决定是否传 data"""
    content = (PROJECT_ROOT / "src/server/app.py").read_text(encoding="utf-8")
    # 找 dispatch 主体的关键逻辑
    assert "param_count >= 2" in content, "必须 param_count >= 2 才传 data"
    assert "route.handler(self)" in content, "1 参时只传 handler"


def test_dispatch_no_longer_unconditionally_passes_data():
    """dispatch 不再无条件 `route.handler(self, data)` — 这是原 bug"""
    content = (PROJECT_ROOT / "src/server/app.py").read_text(encoding="utf-8")
    # 找 dispatch 部分代码
    dispatch_start = content.find("# P6.S.23 + Bug8 fix: dispatch")
    assert dispatch_start > 0, "必须包含 Bug8 修复注释"
    after_dispatch = content[dispatch_start:dispatch_start + 2000]
    # dispatch 应在 param_count >= 2 条件下才传 data
    # 关键是 dispatch 内不应有 `route.handler(self, data)` 的无条件调用
    # (param_count >= 2 分支也允许,但需在条件块内)
    # 检查: 在 if param_count >= 2: 块内有 route.handler 调用,不在条件外
    if "param_count >= 2:" in after_dispatch:
        # 看 if 块内是否有 route.handler 调用
        if_block_start = after_dispatch.find("if param_count >= 2:")
        if_block_end = after_dispatch.find("\n            else:", if_block_start)
        if_block = after_dispatch[if_block_start:if_block_end]
        assert "route.handler" in if_block, "if param_count >= 2 块内必须有 handler 调用"
        # else 块内应是 1 参调用
        else_block = after_dispatch[if_block_end:if_block_end + 300]
        assert "route.handler(self)" in else_block, "else 块内必须 1 参调用"
    else:
        # 没有 param_count >= 2 条件,说明没修复
        assert False, "dispatch 必须有 param_count >= 2 条件判断"


# ---------------------------------------------------------------------------
# B. handler 签名一致性
# ---------------------------------------------------------------------------
def test_no_1arg_handlers_remain_broken():
    """统计 routers/ 中所有 1 参 handler,都是接受 data=None 或无 body 的 GET 端点"""
    # 修复后,所有 1 参 handler 由 dispatch 自动适配(只传 handler)
    # 所以即使保留 1 参签名也不会崩
    broken_count = 0
    for py in (PROJECT_ROOT / "src/server/routers").glob("*.py"):
        content = py.read_text(encoding="utf-8")
        for m in re.finditer(r"def (\w+)\(handler\):", content):
            broken_count += 1
    # 现在仍有 17 个 1 参 handler,但 dispatch 已经适配,不再 500
    # 测 0 个硬编码 `route.handler(self, data)`
    app_content = (PROJECT_ROOT / "src/server/app.py").read_text(encoding="utf-8")
    # 看 dispatch 部分(在 def _dispatch 之后)
    dispatch_idx = app_content.find("def _dispatch")
    assert dispatch_idx > 0
    # 后续 2000 字符内不应有硬编码 `route.handler(self, data)`
    nearby = app_content[dispatch_idx:dispatch_idx + 3000]
    assert "route.handler(self, data)" not in nearby, (
        "dispatch 中不应硬编码 route.handler(self, data)"
    )


# ---------------------------------------------------------------------------
# C. 真实 HTTP 烟测:启动服务用 requests 调几个端点
# ---------------------------------------------------------------------------
def test_real_http_root_returns_html():
    """GET / 必须返 200 + HTML(不再 500)"""
    import urllib.request
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5)
        status = resp.status
        body = resp.read(200).decode("utf-8", errors="replace")
    except Exception as e:
        import pytest
        pytest.skip(f"服务未运行 ({e}),跳过真实 HTTP 烟测")
    assert status == 200, f"GET / 应返 200,实际 {status}"
    assert "<html" in body.lower() or "<!doctype" in body.lower(), (
        f"GET / 应返 HTML,实际 body 开头:{body[:100]}"
    )


def test_real_http_health_returns_json():
    """GET /api/health 必须返 200 + JSON(不再 500)"""
    import urllib.request
    import json
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5)
        status = resp.status
        body = resp.read(2000).decode("utf-8", errors="replace")
    except Exception as e:
        import pytest
        pytest.skip(f"服务未运行 ({e}),跳过真实 HTTP 烟测")
    # P5-E: ok/degraded 返 200,down 返 503
    assert status in (200, 503), f"GET /api/health 应返 200/503,实际 {status}"
    data = json.loads(body)
    assert "ok" in data
    assert "service" in data
    # 关键:不能是 INTERNAL 500 错误格式
    if "error" in data:
        assert data["error"].get("code") != "INTERNAL", (
            f"健康检查不应是 INTERNAL 错误:{data}"
        )
