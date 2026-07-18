"""
P10.B 测试: MCPRegistry transport 字段分发

覆盖:
1. load_config 解析 stdio 配置 → MCPClientConfig
2. load_config 解析 streamable-http 配置 → StreamableHTTPClientConfig
3. 同一 yaml 混编两种 transport,都正确识别
4. 未知 transport 被跳过(警告日志)
5. config 路径不存在的优雅降级
6. 实例化分发:stdio → MCPClient,http → StreamableHTTPClient
7. _make_server_info 根据 transport 选类型
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 8.0) -> bool:
    import urllib.request
    import urllib.error

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(urllib.request.Request(url, method="GET"), timeout=1)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(0.2)
    return False


class _HTTPServerFixture:
    def __init__(self, port: int):
        self.port = port
        self.proc = None

    def start(self) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "mock_http_mcp_server.py"),
             "--port", str(self.port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        if not _wait_for_server(f"http://127.0.0.1:{self.port}/mcp"):
            self.stop()
            raise RuntimeError("HTTP mock 未起来")

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


# ============ 配置解析测试 ============

def test_load_stdio_config():
    """load_config 解析纯 stdio 配置"""
    from mcp import MCPRegistry
    from mcp.client import MCPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: only_stdio
            transport: stdio
            command: python
            args:
              - scripts/mcp_mock_server.py
            connect_timeout_s: 5.0
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        reg = MCPRegistry()
        configs = reg.load_config(path)
        assert len(configs) == 1
        assert isinstance(configs[0], MCPClientConfig)
        assert configs[0].name == "only_stdio"
        assert configs[0].command == "python"
        assert configs[0].connect_timeout_s == 5.0
    finally:
        os.unlink(path)
    print("✅ test_load_stdio_config PASSED")


def test_load_streamable_http_config():
    """load_config 解析纯 streamable-http 配置"""
    from mcp import MCPRegistry
    from mcp.streamable_client import StreamableHTTPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: only_http
            transport: streamable-http
            url: https://example.com/mcp
            headers:
              Authorization: Bearer xxx
            origin: https://custom.example.com
            request_timeout_s: 15.0
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        reg = MCPRegistry()
        configs = reg.load_config(path)
        assert len(configs) == 1
        assert isinstance(configs[0], StreamableHTTPClientConfig)
        assert configs[0].name == "only_http"
        assert configs[0].url == "https://example.com/mcp"
        assert configs[0].transport == "streamable-http"
        assert configs[0].headers.get("Authorization") == "Bearer xxx"
        assert configs[0].origin == "https://custom.example.com"
        assert configs[0].request_timeout_s == 15.0
    finally:
        os.unlink(path)
    print("✅ test_load_streamable_http_config PASSED")


def test_load_mixed_transports():
    """混编 stdio + streamable-http,分发正确"""
    from mcp import MCPRegistry
    from mcp.client import MCPClientConfig
    from mcp.streamable_client import StreamableHTTPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: s1
            transport: stdio
            command: python
            args: [scripts/mcp_mock_server.py]
          - name: h1
            transport: streamable-http
            url: http://127.0.0.1:9999/mcp
          - name: s2
            transport: stdio
            command: python
            args: [other_script.py]
          - name: h2
            transport: streamable-http
            url: http://other.example.com/mcp
            headers:
              Authorization: Bearer yyy
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        reg = MCPRegistry()
        configs = reg.load_config(path)
        assert len(configs) == 4
        # 按声明顺序
        assert isinstance(configs[0], MCPClientConfig) and configs[0].name == "s1"
        assert isinstance(configs[1], StreamableHTTPClientConfig) and configs[1].name == "h1"
        assert isinstance(configs[2], MCPClientConfig) and configs[2].name == "s2"
        assert isinstance(configs[3], StreamableHTTPClientConfig) and configs[3].name == "h2"
        assert configs[3].headers["Authorization"] == "Bearer yyy"
    finally:
        os.unlink(path)
    print("✅ test_load_mixed_transports PASSED")


def test_unknown_transport_skipped():
    """未知 transport 应跳过(不抛异常)"""
    from mcp import MCPRegistry

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: good
            transport: stdio
            command: python
            args: [x.py]
          - name: bad
            transport: telepathy
            url: somewhere
          - name: good2
            transport: streamable-http
            url: http://x/mcp
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        reg = MCPRegistry()
        configs = reg.load_config(path)
        assert len(configs) == 2
        names = {c.name for c in configs}
        assert names == {"good", "good2"}, names
    finally:
        os.unlink(path)
    print("✅ test_unknown_transport_skipped PASSED")


def test_missing_config_returns_empty():
    """config 文件不存在应返空列表(不抛)"""
    from mcp import MCPRegistry

    reg = MCPRegistry()
    configs = reg.load_config("/nonexistent/mcp.yaml")
    assert configs == []
    print("✅ test_missing_config_returns_empty PASSED")


def test_default_transport_is_stdio():
    """未指定 transport 时默认 stdio(向后兼容)"""
    from mcp import MCPRegistry
    from mcp.client import MCPClientConfig

    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: legacy
            command: python
            args: [a.py]
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        reg = MCPRegistry()
        configs = reg.load_config(path)
        assert len(configs) == 1
        assert isinstance(configs[0], MCPClientConfig)
    finally:
        os.unlink(path)
    print("✅ test_default_transport_is_stdio PASSED")


def test_instantiate_dispatch():
    """_instantiate_client 按 config 类型构造对应 client"""
    from mcp import MCPRegistry
    from mcp.client import MCPClient, MCPClientConfig
    from mcp.streamable_client import StreamableHTTPClient, StreamableHTTPClientConfig

    reg = MCPRegistry()
    s_client, s_kind = reg._instantiate_client(
        MCPClientConfig(name="s", command="python", args=["a.py"])
    )
    h_client, h_kind = reg._instantiate_client(
        StreamableHTTPClientConfig(name="h", url="http://x/mcp")
    )
    assert isinstance(s_client, MCPClient)
    assert s_kind == "stdio"
    assert isinstance(h_client, StreamableHTTPClient)
    assert h_kind == "streamable-http"
    # cleanup
    try:
        s_client._cleanup()
    except Exception:
        pass
    try:
        h_client.disconnect()
    except Exception:
        pass
    print("✅ test_instantiate_dispatch PASSED")


def test_make_server_info_dispatch():
    """_make_server_info 按 transport 字段选类型"""
    from mcp.registry import _make_server_info
    from mcp.client import MCPServerInfo
    from mcp.streamable_client import StreamableHTTPServerInfo

    s_info = _make_server_info("s1", "stdio", "python x.py")
    h_info = _make_server_info("h1", "streamable-http", "http://x/mcp")
    assert isinstance(s_info, MCPServerInfo)
    assert isinstance(h_info, StreamableHTTPServerInfo)
    assert s_info.command == "python x.py"
    assert h_info.url == "http://x/mcp"
    assert s_info.status == "connecting"
    print("✅ test_make_server_info_dispatch PASSED")


# ============ 端到端:真实连 http server ============

def test_registry_connect_http_e2e():
    """MCPRegistry 能真实连 mock HTTP server,tools 注册到本地 ToolRegistry"""
    from mcp import MCPRegistry
    from agent.tools import get_registry as get_tool_registry
    from mcp.client import MCPTool
    from mcp.streamable_client import StreamableHTTPClientConfig

    port = _free_port()
    fix = _HTTPServerFixture(port)
    fix.start()
    try:
        yaml_text = textwrap.dedent(f"""
            mcp_servers:
              - name: reg_http_test
                transport: streamable-http
                url: http://127.0.0.1:{port}/mcp
                request_timeout_s: 5.0
                connect_timeout_s: 5.0
        """).strip()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_text)
            path = f.name
        try:
            reg = MCPRegistry()
            configs = reg.load_config(path)
            assert len(configs) == 1
            assert isinstance(configs[0], StreamableHTTPClientConfig)

            # 用 connect_all_blocking 异步入口测一下直接调用路径
            # 这里直接同步调 connect_all_async 风格
            import asyncio

            async def _run():
                await reg.connect_all_async(configs)
                # 重新跑一遍确保状态写入
                pass

            asyncio.run(_run())
            # 校验 status
            status = reg.status()
            assert status["servers_count"] == 1
            server = status["servers"][0]
            assert server["name"] == "reg_http_test"
            assert server["transport"] == "streamable-http"
            assert server["status"] == "connected", f"应为 connected, 实际 {server}"
            assert server["tools_count"] == 3
            assert server.get("session_id"), "应有 session id"
            # 校验 tools 注册
            assert status["tools_count"] == 3
            tool_names = {t["name"] for t in status["tools"]}
            assert tool_names == {"mock_echo", "mock_weather", "mock_carbon"}
            # 校验 tool 也注册到了本地 ToolRegistry
            tool_reg = get_tool_registry()
            all_tools = tool_reg.list_all()
            mcp_tools = [n for n in all_tools if "reg_http_test" in n]
            assert len(mcp_tools) >= 3, f"本地 ToolRegistry 应有 3 个 mcp tool, 实际 {mcp_tools}"
            reg.shutdown()
        finally:
            os.unlink(path)
    finally:
        fix.stop()
    print("✅ test_registry_connect_http_e2e PASSED")


def test_registry_mixed_connect_e2e():
    """混编 stdio + http:两种 client 都跑通"""
    from mcp import MCPRegistry

    port = _free_port()
    fix = _HTTPServerFixture(port)
    fix.start()
    try:
        stdio_script = str(ROOT / "scripts" / "mcp_mock_server.py")
        yaml_text = textwrap.dedent(f"""
            mcp_servers:
              - name: mixed_stdio
                transport: stdio
                command: python
                args:
                  - {stdio_script}
              - name: mixed_http
                transport: streamable-http
                url: http://127.0.0.1:{port}/mcp
                request_timeout_s: 5.0
        """).strip()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_text)
            path = f.name
        try:
            reg = MCPRegistry()
            configs = reg.load_config(path)
            assert len(configs) == 2

            import asyncio

            asyncio.run(reg.connect_all_async(configs))
            status = reg.status()
            assert status["servers_count"] == 2
            # 两种 transport 都连上
            kinds = {s["transport"] for s in status["servers"]}
            assert kinds == {"stdio", "streamable-http"}, kinds
            # 都 connected
            assert all(s["status"] == "connected" for s in status["servers"]), status
            # 总共 6 tools(每个 server 3 个)
            assert status["tools_count"] == 6, status["tools_count"]
            reg.shutdown()
        finally:
            os.unlink(path)
    finally:
        fix.stop()
    print("✅ test_registry_mixed_connect_e2e PASSED")


if __name__ == "__main__":
    test_load_stdio_config()
    test_load_streamable_http_config()
    test_load_mixed_transports()
    test_unknown_transport_skipped()
    test_missing_config_returns_empty()
    test_default_transport_is_stdio()
    test_instantiate_dispatch()
    test_make_server_info_dispatch()
    test_registry_connect_http_e2e()
    test_registry_mixed_connect_e2e()
    print("\n🎉 All P10.B Registry transport dispatch tests PASSED")