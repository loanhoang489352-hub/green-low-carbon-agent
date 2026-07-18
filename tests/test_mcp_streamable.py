"""
P10.B 测试: MCP Streamable HTTP 客户端

覆盖:
1. mock HTTP server 能起、能返 tools/list
2. StreamableHTTPClient.connect() 成功,带 session id + protocol header
3. list_tools() 拿到 3 个 tool(echo/weather/carbon)
4. call_tool() 真实调用工具,结果正确
5. Origin 校验生效(403)
6. 不存在的 server 优雅降级(error 不抛)
7. 协议版本头发送正确

依赖: scripts/mock_http_mcp_server.py(同进程用 ThreadingHTTPServer 拉起)
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 找到 mock server 脚本
MOCK_SCRIPT = ROOT / "scripts" / "mock_http_mcp_server.py"


def _free_port() -> int:
    """找一个空闲端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 8.0) -> bool:
    """等 server 起来(GET 返任意响应即可)"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            urllib.request.urlopen(req, timeout=1)
            return True
        except urllib.error.HTTPError:
            return True  # 405 也算活
        except Exception:
            time.sleep(0.2)
    return False


class _MockServerFixture:
    """启停 mock HTTP MCP server 的 fixture"""

    def __init__(self, port: int):
        self.port = port
        self.proc: subprocess.Popen = None

    def start(self) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, str(MOCK_SCRIPT), "--port", str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        if not _wait_for_server(f"http://127.0.0.1:{self.port}/mcp"):
            self.stop()
            raise RuntimeError(f"mock HTTP MCP server 未在端口 {self.port} 起来")

    def stop(self) -> None:
        if not self.proc:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None


# ============ 单元测试 ============

def test_module_imports():
    """Streamable HTTP 模块可 import"""
    from mcp import (
        StreamableHTTPClient,
        StreamableHTTPClientConfig,
        StreamableHTTPServerInfo,
        PROTOCOL_VERSION,
        validate_origin,
    )
    from mcp.streamable_client import StreamableHTTPClient as _C
    assert _C is StreamableHTTPClient
    assert PROTOCOL_VERSION == "2025-11-25"
    # validate_origin 基础校验
    assert validate_origin("https://a.com", []) is True  # 空白名单不限制
    assert validate_origin(None, ["https://a.com"]) is False
    assert validate_origin("https://a.com", ["https://a.com"]) is True
    assert validate_origin("https://b.com", ["https://a.com"]) is False
    print("✅ test_module_imports PASSED")


def test_validate_origin_helper():
    """validate_origin 边界值"""
    from mcp import validate_origin
    # 空 allowed = 不限制
    assert validate_origin("anything", []) is True
    assert validate_origin(None, []) is True
    # 非空 allowed:必须命中
    assert validate_origin("https://x.com", ["https://x.com"]) is True
    assert validate_origin("https://y.com", ["https://x.com"]) is False
    assert validate_origin(None, ["https://x.com"]) is False
    # 多白名单
    assert validate_origin("https://y.com", ["https://x.com", "https://y.com"]) is True
    print("✅ test_validate_origin_helper PASSED")


def test_connect_and_list_tools():
    """StreamableHTTPClient.connect() + list_tools()"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    fix = _MockServerFixture(port)
    fix.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="mock_http",
            url=f"http://127.0.0.1:{port}/mcp",
            connect_timeout_s=5.0,
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect(), f"connect 应成功, error={client.error}"
            assert client.connected
            assert client.session_id, "initialize 后应有 session id"
            # serverInfo 应记录
            assert client._server_info.get("serverInfo", {}).get("name") == "mock-http-mcp-server"
            # protocol version
            assert client._protocol_version == "2025-11-25"
            # 列出 3 个 tool
            tools = client.list_tools()
            assert len(tools) == 3, f"应有 3 tools, 实际 {len(tools)}"
            names = {t.name for t in tools}
            assert names == {"mock_echo", "mock_weather", "mock_carbon"}, names
            # server_name 应被填充
            assert all(t.server_name == "mock_http" for t in tools)
        finally:
            client.disconnect()
            assert not client.connected
    finally:
        fix.stop()
    print("✅ test_connect_and_list_tools PASSED")


def test_call_tool_echo():
    """call_tool('mock_echo') 应返回显文本"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    fix = _MockServerFixture(port)
    fix.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="echo_test",
            url=f"http://127.0.0.1:{port}/mcp",
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            result = client.call_tool("mock_echo", {"text": "hello streamable"})
            assert result.get("success"), f"应成功, 实际 {result}"
            content = result["content"]
            # MCP 标准: {"content": [{"type": "text", "text": "..."}]}
            assert "content" in content
            text = content["content"][0]["text"]
            assert text == "echo: hello streamable", f"实际: {text}"
        finally:
            client.disconnect()
    finally:
        fix.stop()
    print("✅ test_call_tool_echo PASSED")


def test_call_tool_carbon():
    """call_tool('mock_carbon') 应计算碳排放"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    fix = _MockServerFixture(port)
    fix.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="carbon_test",
            url=f"http://127.0.0.1:{port}/mcp",
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            # 10km cycling → 0
            r1 = client.call_tool("mock_carbon", {"distance_km": 10, "mode": "cycling"})
            assert r1["success"]
            t1 = r1["content"]["content"][0]["text"]
            data1 = json.loads(t1)
            assert data1["carbon_kg"] == 0
            # 10km car → 2.1
            r2 = client.call_tool("mock_carbon", {"distance_km": 10, "mode": "car"})
            assert r2["success"]
            data2 = json.loads(r2["content"]["content"][0]["text"])
            assert data2["carbon_kg"] == 2.1
        finally:
            client.disconnect()
    finally:
        fix.stop()
    print("✅ test_call_tool_carbon PASSED")


def test_call_tool_not_connected():
    """未 connect 时 call_tool 应返失败(优雅降级)"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    cfg = StreamableHTTPClientConfig(
        name="not_connected",
        url="http://127.0.0.1:1/mcp",
    )
    client = StreamableHTTPClient(cfg)
    # 不调 connect
    result = client.call_tool("mock_echo", {"text": "x"})
    assert not result.get("success")
    assert "not connected" in result.get("error", "")
    tools = client.list_tools()
    assert tools == []
    print("✅ test_call_tool_not_connected PASSED")


def test_connect_to_unreachable_server():
    """连不上的 server 应优雅失败(不抛异常)"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    cfg = StreamableHTTPClientConfig(
        name="unreachable",
        url="http://127.0.0.1:1/mcp",  # 端口 1 必不通
        connect_timeout_s=2.0,
        request_timeout_s=2.0,
        verify_ssl=False,
    )
    client = StreamableHTTPClient(cfg)
    ok = client.connect()
    assert not ok, "应失败"
    assert not client.connected
    assert client.error, "应有 error 信息"
    assert "Timeout" in client.error or "Connection" in client.error or "connect" in client.error.lower(), \
        f"error 描述应含网络错误, 实际 {client.error}"
    print("✅ test_connect_to_unreachable_server PASSED")


def test_disabled_by_config():
    """enabled=false 时 connect 应立即返 False"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    cfg = StreamableHTTPClientConfig(
        name="disabled",
        url="http://127.0.0.1:8765/mcp",
        enabled=False,
    )
    client = StreamableHTTPClient(cfg)
    assert not client.connect()
    assert "disabled" in (client.error or "")
    print("✅ test_disabled_by_config PASSED")


def test_origin_validation_on_server_side():
    """Origin 白名单在 server 侧生效(403)"""
    port = _free_port()
    fix = _MockServerFixture(port)
    fix.start()
    try:
        # 直接用 urllib 发带恶意 Origin 的 POST
        bad_origin = "https://evil.example.com"
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/mcp",
            data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": bad_origin,
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            assert False, "应被 403 拒绝"
        except urllib.error.HTTPError as e:
            assert e.code == 403, f"应 403, 实际 {e.code}"
    finally:
        fix.stop()
    print("✅ test_origin_validation_on_server_side PASSED")


def test_protocol_version_header():
    """握手后请求应带 MCP-Protocol-Version 头"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    fix = _MockServerFixture(port)
    fix.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="proto_test",
            url=f"http://127.0.0.1:{port}/mcp",
            protocol_version="2025-11-25",
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            # 用内部 _build_headers 验证
            headers = client._build_headers()
            assert headers.get("MCP-Protocol-Version") == "2025-11-25"
            assert headers.get("Mcp-Session-Id") == client.session_id
            assert headers.get("Origin") == "https://green-low-carbon-agent.local"
            # Accept 必须含两种
            accept = headers.get("Accept", "")
            assert "application/json" in accept
            assert "text/event-stream" in accept
        finally:
            client.disconnect()
    finally:
        fix.stop()
    print("✅ test_protocol_version_header PASSED")


def test_custom_headers_and_origin():
    """自定义 Origin + headers 应被发送"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    cfg = StreamableHTTPClientConfig(
        name="custom",
        url="http://127.0.0.1:9999/mcp",
        origin="https://custom.example.com",
        headers={"X-Custom-Token": "abc123", "Authorization": "Bearer xyz"},
    )
    client = StreamableHTTPClient(cfg)
    headers = client._build_headers()
    assert headers.get("Origin") == "https://custom.example.com"
    assert headers.get("X-Custom-Token") == "abc123"
    assert headers.get("Authorization") == "Bearer xyz"
    print("✅ test_custom_headers_and_origin PASSED")


def test_oauth_bearer_injection():
    """oauth_token 应自动注入 Authorization: Bearer ..."""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    cfg = StreamableHTTPClientConfig(
        name="oauth_test",
        url="http://127.0.0.1:9999/mcp",
        oauth_token="tok_abc",
    )
    client = StreamableHTTPClient(cfg)
    headers = client._build_headers()
    assert headers.get("Authorization") == "Bearer tok_abc"
    # 自定义 Authorization 应优先
    cfg2 = StreamableHTTPClientConfig(
        name="oauth_test2",
        url="http://127.0.0.1:9999/mcp",
        oauth_token="tok_abc",
        headers={"Authorization": "Bearer custom"},
    )
    client2 = StreamableHTTPClient(cfg2)
    h2 = client2._build_headers()
    assert h2.get("Authorization") == "Bearer custom"
    print("✅ test_oauth_bearer_injection PASSED")


def test_oauth_refresh_stub():
    """未配 oauth_token_url 时 refresh 应失败(明确失败,不抛)"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    cfg = StreamableHTTPClientConfig(
        name="oauth_stub",
        url="http://127.0.0.1:9999/mcp",
    )
    client = StreamableHTTPClient(cfg)
    assert not client.refresh_oauth_token()
    assert "oauth not configured" in (client.error or "")
    print("✅ test_oauth_refresh_stub PASSED")


def test_backward_compat_stdio_client():
    """P10.B: 不破坏现有 stdio MCPClient(P6.S.16 接口稳定)"""
    from mcp import MCPClient, MCPClientConfig

    cfg = MCPClientConfig(
        name="stdio_backcompat",
        command=sys.executable,
        args=[str(MOCK_SCRIPT.parent / "mcp_mock_server.py")],
        connect_timeout_s=5.0,
        request_timeout_s=5.0,
    )
    client = MCPClient(cfg)
    try:
        assert client.connect(), f"stdio client 应仍能 connect, error={client.error}"
        tools = client.list_tools()
        assert len(tools) == 3
        result = client.call_tool("mock_echo", {"text": "backcompat"})
        assert result["success"]
    finally:
        client.disconnect()
    print("✅ test_backward_compat_stdio_client PASSED")


if __name__ == "__main__":
    test_module_imports()
    test_validate_origin_helper()
    test_connect_and_list_tools()
    test_call_tool_echo()
    test_call_tool_carbon()
    test_call_tool_not_connected()
    test_connect_to_unreachable_server()
    test_disabled_by_config()
    test_origin_validation_on_server_side()
    test_protocol_version_header()
    test_custom_headers_and_origin()
    test_oauth_bearer_injection()
    test_oauth_refresh_stub()
    test_backward_compat_stdio_client()
    print("\n🎉 All P10.B Streamable HTTP tests PASSED")