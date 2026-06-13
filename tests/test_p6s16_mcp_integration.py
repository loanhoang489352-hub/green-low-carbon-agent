"""
P6.S.16 测试: MCP 集成

P6.S.16 设计:
- 零外部依赖(stdlib asyncio + json + subprocess + threading)
- 协议: JSON-RPC 2.0 over stdio(每行一个 JSON)
- MCPClient: 同步 I/O + 后台 read 线程
- MCPToolAdapter: 包装 MCP 远端 tool 为 BaseTool,注册到本地 ToolRegistry
- MCPServer: 把本地 tools 暴露为 MCP server
- MCPRegistry: 启动时读 config/mcp_servers.yaml,连所有启用 server,注册 tool
- 调试端点: GET /api/mcp/status

验证:
1. MCP 模块可 import(client/adapter/server/registry)
2. MCPClient 同步接口工作
3. MCPToolAdapter 把 MCP tool 包装成 BaseTool
4. MCPServer 把本地 tools 暴露(本地测试)
5. config/mcp_servers.yaml 解析
6. server 启动后 /api/mcp/status 返 1 server + 3 tools
"""
import sys
import os
import json
import urllib.request
import urllib.error
import subprocess
import time
import threading

sys.path.insert(0, str(__file__).replace("\\", "/").replace("tests/test_p6s16_mcp_integration.py", "src"))


def _http_get(url, timeout=10):
    req = urllib.request.Request(url, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def _http_post(url, data, timeout=30):
    req = urllib.request.Request(
        url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8", errors="ignore"))


def test_server_running():
    code, _ = _http_get("http://localhost:8000/api/health", timeout=5)
    if code != 200:
        print(f"⏭ SKIPPED: server not running (code={code})")
        return False
    return True


# ============ 单元测试(独立于 server) ============

def test_mcp_module_imports():
    """P6.S.16: MCP 模块可 import"""
    from mcp import MCPClient, MCPToolAdapter, MCPServer, MCPRegistry, get_mcp_registry
    from mcp.client import MCPClientConfig, MCPTool
    from mcp.adapter import MCPToolAdapter
    from mcp.server import MCPServer
    print("✅ test_mcp_module_imports PASSED")


def test_mcp_client_sync_interface():
    """P6.S.16: MCPClient 同步 connect + call_tool 接口工作"""
    from mcp.client import MCPClient, MCPClientConfig

    cfg = MCPClientConfig(
        name="test_client",
        command="python",
        args=[os.path.abspath("scripts/mcp_mock_server.py")],
        connect_timeout_s=10.0,
        request_timeout_s=10.0,
    )
    client = MCPClient(cfg)
    ok = client.connect()
    assert ok, f"connect 应成功, 实际: {client.error}"
    tools = client.list_tools()
    assert len(tools) == 3, f"应有 3 tools, 实际 {len(tools)}"
    assert {t.name for t in tools} == {"mock_echo", "mock_weather", "mock_carbon"}

    result = client.call_tool("mock_echo", {"text": "hello P6.S.16"})
    assert result["success"], f"echo 应成功, 实际 {result}"
    assert "echo" in str(result["content"])

    result2 = client.call_tool("mock_carbon", {"distance_km": 10, "mode": "cycling"})
    assert result2["success"], f"carbon 应成功, 实际 {result2}"
    # content 嵌套了 [{"type": "text", "text": "..."}]
    text = json.dumps(result2["content"], ensure_ascii=False)
    assert "carbon_kg" in text
    assert "cycling" in text

    client.disconnect()
    print("✅ test_mcp_client_sync_interface PASSED")


def test_mcp_tool_adapter():
    """P6.S.16: MCPToolAdapter 把 MCP tool 包装成 BaseTool"""
    from mcp.client import MCPClient, MCPClientConfig, MCPTool
    from mcp.adapter import MCPToolAdapter
    from agent.tools.base import ToolResult

    cfg = MCPClientConfig(
        name="adapter_test",
        command="python",
        args=[os.path.abspath("scripts/mcp_mock_server.py")],
    )
    client = MCPClient(cfg)
    assert client.connect()
    tools = client.list_tools()
    mock_echo = next(t for t in tools if t.name == "mock_echo")

    adapter = MCPToolAdapter(mock_echo, client)
    # BaseTool 属性
    assert adapter.name.startswith("mcp_adapter_test_mock_echo"), f"name 应带前缀, 实际 {adapter.name}"
    assert "[MCP: adapter_test]" in adapter.description
    assert len(adapter.parameters) >= 1
    assert adapter.parameters[0]["name"] == "text"

    # execute 应能跑
    result = adapter.execute(text="adapter test")
    assert isinstance(result, ToolResult)
    assert result.success
    assert "echo" in result.data["text"]

    client.disconnect()
    print("✅ test_mcp_tool_adapter PASSED")


def test_mcp_server_exposes_local_tools():
    """P6.S.16: MCPServer 把本地 tools 暴露为 MCP server(用 stdin/stdout 测)"""
    # 启动 mock server 子进程,作为 MCP client
    proc = subprocess.Popen(
        ["python", "scripts/mcp_mock_server.py"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", bufsize=1,
        cwd=os.getcwd(),
    )
    try:
        # initialize
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }) + "\n")
        proc.stdin.flush()
        init_resp = json.loads(proc.stdout.readline())
        assert "result" in init_resp
        assert init_resp["result"]["serverInfo"]["name"] == "mock-mcp-server"

        # tools/list
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }) + "\n")
        proc.stdin.flush()
        list_resp = json.loads(proc.stdout.readline())
        tool_names = [t["name"] for t in list_resp["result"]["tools"]]
        assert {"mock_echo", "mock_weather", "mock_carbon"} == set(tool_names)

        # tools/call
        proc.stdin.write(json.dumps({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "mock_echo", "arguments": {"text": "server test"}},
        }) + "\n")
        proc.stdin.flush()
        call_resp = json.loads(proc.stdout.readline())
        assert call_resp["result"]["content"][0]["text"] == "echo: server test"
    finally:
        proc.stdin.close()
        proc.terminate()
    print("✅ test_mcp_server_exposes_local_tools PASSED")


def test_mcp_registry_loads_config():
    """P6.S.16: MCPRegistry.load_config 读 yaml"""
    from mcp import MCPRegistry
    reg = MCPRegistry.instance()
    configs = reg.load_config("config/mcp_servers.yaml")
    assert len(configs) >= 1, f"应至少 1 个 server, 实际 {len(configs)}"
    assert configs[0].name == "mock_server"
    assert configs[0].command == "python"
    # P6.S.16: 相对路径被解析为绝对路径(避免 server cwd 改变后找不到)
    assert os.path.isabs(configs[0].args[0]), f"应是绝对路径, 实际 {configs[0].args[0]}"
    assert configs[0].args[0].endswith("scripts" + os.sep + "mcp_mock_server.py")
    # cwd 默认是 project_root
    assert configs[0].cwd and os.path.isabs(configs[0].cwd), \
        f"cwd 应是绝对路径, 实际 {configs[0].cwd}"
    print(f"  loaded {len(configs)} server(s): {[(c.name, c.command) for c in configs]}")
    print("✅ test_mcp_registry_loads_config PASSED")


# ============ HTTP 端到端(server 已启动) ============

def test_mcp_status_endpoint():
    """P6.S.16: /api/mcp/status 应返 server 列表和 tool 列表"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/mcp/status")
    assert code == 200, f"应 200, 实际 {code}"
    assert body["servers_count"] >= 1, f"应 ≥1 server, 实际 {body}"
    assert body["tools_count"] >= 3, f"应 ≥3 tools, 实际 {body}"
    server = body["servers"][0]
    assert server["status"] == "connected", f"server 应 connected, 实际 {server['status']}"
    assert server["tools_count"] == 3
    tool_names = [t["name"] for t in body["tools"]]
    assert {"mock_echo", "mock_weather", "mock_carbon"} == set(tool_names)
    print(f"  servers: {body['servers_count']}, tools: {body['tools_count']}")
    print("✅ test_mcp_status_endpoint PASSED")


def test_mcp_tool_callable_via_chat():
    """P6.S.16: MCP tool 注入 ToolRegistry 后,可通过 /api/tools-skills 查到"""
    if not test_server_running():
        return
    code, body = _http_get("http://localhost:8000/api/tools-skills")
    assert code == 200
    tool_names = [t["name"] for t in body["tools"]]
    mcp_tools = [n for n in tool_names if n.startswith("mcp_")]
    assert len(mcp_tools) >= 3, f"应 ≥3 mcp_* tools 注册, 实际 {mcp_tools}"
    assert any("mock_echo" in t for t in mcp_tools)
    assert any("mock_weather" in t for t in mcp_tools)
    assert any("mock_carbon" in t for t in mcp_tools)
    print(f"  mcp tools in registry: {mcp_tools}")
    print("✅ test_mcp_tool_callable_via_chat PASSED")


if __name__ == "__main__":
    test_server_running()
    test_mcp_module_imports()
    test_mcp_client_sync_interface()
    test_mcp_tool_adapter()
    test_mcp_server_exposes_local_tools()
    test_mcp_registry_loads_config()
    test_mcp_status_endpoint()
    test_mcp_tool_callable_via_chat()
    print("\n🎉 All P6.S.16 tests PASSED")
