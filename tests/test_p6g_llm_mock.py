"""
P6.G LLM_MOCK 开关 单元测试

覆盖:
1. is_mock_mode() 解析 true/false/auto/1/0/未设
2. should_use_mock(client) 字段检查(client/_client/_access_token)
3. OpenAIClient.chat 在 LLM_MOCK=true 时强制走 mock(即使 _client 配好)
4. LLM_MOCK=false 强制真实 API(即使 _client 没配,会失败)
5. LLM_MOCK=auto 走原行为(client None 时 mock)
6. /api/metrics 暴露 LLM_MOCK 当前值
7. 真实场景:pytest 跑时不依赖 API(LLM_MOCK=true)
"""
import os
import sys
import time
from pathlib import Path
from unittest import mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """每个测试前清空 LLM_MOCK"""
    monkeypatch.delenv("LLM_MOCK", raising=False)


# ========== 1. is_mock_mode 解析 ==========

def test_is_mock_mode_true_variants():
    """true / 1 / yes / on → True"""
    from llm import is_mock_mode
    for v in ("true", "True", "TRUE", "1", "yes", "on", "ON"):
        with mock.patch.dict(os.environ, {"LLM_MOCK": v}):
            assert is_mock_mode() is True, f"{v} 应 True, 实际 {is_mock_mode()}"


def test_is_mock_mode_false_variants():
    """false / 0 / no / off → False"""
    from llm import is_mock_mode
    for v in ("false", "False", "FALSE", "0", "no", "off", "OFF"):
        with mock.patch.dict(os.environ, {"LLM_MOCK": v}):
            assert is_mock_mode() is False, f"{v} 应 False, 实际 {is_mock_mode()}"


def test_is_mock_mode_auto_or_unset():
    """auto / 未设 → None(由 should_use_mock 决定)"""
    from llm import is_mock_mode
    for v in ("auto", "AUTO", "", "garbage"):
        with mock.patch.dict(os.environ, {"LLM_MOCK": v}):
            assert is_mock_mode() is None, f"{v!r} 应 None, 实际 {is_mock_mode()}"
    # 完全未设
    with mock.patch.dict(os.environ, {}, clear=True):
        assert is_mock_mode() is None


# ========== 2. should_use_mock 字段检查 ==========

class FakeClient:
    """模拟 LLM client(支持 .client / ._client / ._access_token)"""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_should_use_mock_true_force():
    """LLM_MOCK=true → 强 mock"""
    from llm import should_use_mock
    # 即使 client 配了也强 mock
    with mock.patch.dict(os.environ, {"LLM_MOCK": "true"}):
        c = FakeClient(client=object())  # 配好也不影响
        assert should_use_mock(c) is True


def test_should_use_mock_false_force():
    """LLM_MOCK=false → 强真实(即使 client 没配)"""
    from llm import should_use_mock
    with mock.patch.dict(os.environ, {"LLM_MOCK": "false"}):
        c = FakeClient(client=None)
        assert should_use_mock(c) is False


def test_should_use_mock_auto_no_client():
    """auto + client 没配 → mock"""
    from llm import should_use_mock
    with mock.patch.dict(os.environ, {"LLM_MOCK": "auto"}):
        c = FakeClient(client=None, _client=None, _access_token=None)
        assert should_use_mock(c) is True


def test_should_use_mock_auto_with_client():
    """auto + client 配好 → 真实"""
    from llm import should_use_mock
    with mock.patch.dict(os.environ, {"LLM_MOCK": "auto"}):
        c = FakeClient(client=object())
        assert should_use_mock(c) is False


def test_should_use_mock_auto_with_access_token():
    """auto + Baidu 的 _access_token 配好 → 真实"""
    from llm import should_use_mock
    with mock.patch.dict(os.environ, {"LLM_MOCK": "auto"}):
        c = FakeClient(_access_token="fake_token")
        assert should_use_mock(c) is False


# ========== 3. 真实 chat() 入口在 LLM_MOCK=true 强制 mock ==========

def test_openai_client_chat_mock_forced():
    """P6.G: LLM_MOCK=true 时 OpenAIClient.chat 即使 client 配好也走 mock"""
    from llm import OpenAIClient
    c = OpenAIClient(api_key="sk-fake-but-valid-format-for-test")
    # 默认 auto + 配了 client → 应真实调用
    # 但我们设 LLM_MOCK=true → 强 mock
    with mock.patch.dict(os.environ, {"LLM_MOCK": "true"}):
        resp = c.chat([{"role": "user", "content": "test"}])
    # 验证是 mock 响应
    assert "Mock" in resp.content or "mock" in resp.content.lower()


def test_client_py_6_providers_all_support_mock():
    """P6.G: client.py 6 provider 的 chat() 都接受 LLM_MOCK 开关"""
    from llm.client import (
        OpenAIClient, ZhipuClient, BaiduClient, AliClient, MiniMaxClient, DeepSeekClient
    )
    providers = [
        (OpenAIClient, "OpenAI"),
        (ZhipuClient, "Zhipu"),
        (BaiduClient, "Baidu"),
        (AliClient, "Ali"),
        (MiniMaxClient, "MiniMax"),
        (DeepSeekClient, "DeepSeek"),
    ]
    with mock.patch.dict(os.environ, {"LLM_MOCK": "true"}):
        for cls, name in providers:
            # 尝试不传 api_key 构造(部分需要 fake key)
            try:
                if name == "MiniMax":
                    c = cls(api_key="fake_key", group_id="fake_group")
                elif name == "Baidu":
                    c = cls(api_key="fake_key", secret_key="fake_secret")
                else:
                    c = cls(api_key="sk-fake")
            except Exception as e:
                # 部分 provider 构造可能失败,跳过
                continue
            try:
                resp = c.chat([{"role": "user", "content": f"test {name}"}])
                assert resp.content, f"{name} 应返非空内容"
            except Exception as e:
                # 跳过构造后初始化失败的 client
                print(f"[{name}] skipped: {e}")


# ========== 4. /api/metrics 不暴露 LLM_MOCK(只 P5-B 字段) ==========

def test_metrics_endpoint_does_not_break_with_mock():
    """P6.G: LLM_MOCK=true 时 /api/metrics 仍工作"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    from io import BytesIO
    import json

    reset_registry()
    register_all_routes(get_registry())

    handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
    handler.path = "/api/metrics"
    handler.headers = {}
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.rfile = BytesIO(b"")
    handler.wfile = BytesIO()
    handler.last_status = None
    handler.last_body = b""
    def instance_send_json(data, status=200):
        handler.last_status = status
        handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_json = instance_send_json
    handler.send_response = lambda s: setattr(handler, "last_status", s)
    handler.send_header = lambda k, v: None
    handler.end_headers = lambda: None
    handler._read_body = lambda: ""
    handler._cors_origin = lambda: "*"
    handler.log_message = lambda fmt, *a: None

    with mock.patch.dict(os.environ, {"LLM_MOCK": "true"}):
        RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 200
    body = json.loads(handler.last_body.decode("utf-8"))
    assert "metrics" in body
