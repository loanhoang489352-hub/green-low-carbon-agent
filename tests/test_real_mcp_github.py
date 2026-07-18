"""
P11.C 测试: GitHub MCP server 接入

模拟一个本地的 GitHub-like MCP server(3 个真实 tool:list_repos / create_issue / get_file_contents),
验证:
1. StreamableHTTPClient 能连接该 mock server,带 ${GITHUB_TOKEN} 后的 Authorization 头
2. 列出 github MCP server 上的 tools(模拟真实 GitHub MCP 工具集)
3. 通过 MCPRegistry 加载真实 yaml(github enabled=true) + 启动 mock server,
   工具自动注册到本地 ToolRegistry,可在 /api/tools-skills 看到 mcp_github_* 前缀
4. 调用 list_repos 工具返回模拟仓库列表
5. 调用 create_issue 工具返回模拟 issue 对象
6. 调用 get_file_contents 工具返回模拟文件内容
7. token 错误时优雅失败(401-style)

零依赖真实 GITHUB_TOKEN:本地 mock server 验任意 bearer 字符串均放行
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

PROTOCOL_VERSION = "2025-11-25"
GITHUB_MOCK_SERVER_INFO = {
    "name": "github-mcp-mock",
    "version": "1.0.0",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ============ GitHub-like MCP server 内联实现 ============

def _gh_tools_list() -> dict:
    """模拟 GitHub MCP server 暴露的 3 个 tool(与 github/github-mcp-server 真实接口对齐)"""
    return {
        "tools": [
            {
                "name": "list_repos",
                "description": "List GitHub repositories for the authenticated user",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "visibility": {
                            "type": "string",
                            "enum": ["all", "public", "private"],
                            "description": "Filter by visibility",
                        },
                        "limit": {"type": "number", "description": "Max repos to return"},
                    },
                },
            },
            {
                "name": "create_issue",
                "description": "Create a new issue in a GitHub repository",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string", "description": "Repo owner"},
                        "repo": {"type": "string", "description": "Repo name"},
                        "title": {"type": "string", "description": "Issue title"},
                        "body": {"type": "string", "description": "Issue body (markdown)"},
                    },
                    "required": ["owner", "repo", "title"],
                },
            },
            {
                "name": "get_file_contents",
                "description": "Get the contents of a file or directory in a repository",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "repo": {"type": "string"},
                        "path": {"type": "string", "description": "File path"},
                        "ref": {"type": "string", "description": "Branch/tag/SHA"},
                    },
                    "required": ["owner", "repo", "path"],
                },
            },
        ]
    }


def _gh_tools_call(name: str, arguments: dict) -> dict:
    """tools/call 业务逻辑(模拟 GitHub MCP)"""
    if name == "list_repos":
        visibility = arguments.get("visibility", "all")
        limit = int(arguments.get("limit", 30))
        repos = [
            {"name": "green-low-carbon-agent", "stars": 42, "language": "Python", "visibility": "public"},
            {"name": "policy-rag-pipeline", "stars": 18, "language": "Python", "visibility": "public"},
            {"name": "ccer-toolkit", "stars": 7, "language": "Python", "visibility": "private"},
        ]
        if visibility != "all":
            repos = [r for r in repos if r["visibility"] == visibility]
        repos = repos[:limit]
        return {
            "content": [
                {"type": "text", "text": json.dumps({"count": len(repos), "repos": repos}, ensure_ascii=False)}
            ],
            "isError": False,
        }
    if name == "create_issue":
        owner = arguments.get("owner", "?")
        repo = arguments.get("repo", "?")
        title = arguments.get("title", "")
        body = arguments.get("body", "")
        issue = {
            "number": 123,
            "html_url": f"https://github.com/{owner}/{repo}/issues/123",
            "title": title,
            "body": body,
            "state": "open",
        }
        return {
            "content": [
                {"type": "text", "text": json.dumps(issue, ensure_ascii=False)}
            ],
            "isError": False,
        }
    if name == "get_file_contents":
        path = arguments.get("path", "")
        content = f"# {path}\n\nThis is mock content for {path}.\n"
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {"path": path, "encoding": "utf-8", "content": content},
                        ensure_ascii=False,
                    ),
                }
            ],
            "isError": False,
        }
    return {"error": {"code": -32602, "message": f"Tool not found: {name}"}}


class _GitHubMCPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args):
        # 静默日志(测试时不需要)
        pass

    def _check_auth(self) -> bool:
        """简单 bearer 校验:任何非空 token 都通过(mock)"""
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            self._send_error(401, -32000, "Missing Authorization")
            return False
        token = auth[len("Bearer "):]
        if not token:
            self._send_error(401, -32000, "Empty token")
            return False
        return True

    def _send_json(self, status: int, body: dict, session_id: str | None = None) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, status: int, code: int, message: str) -> None:
        self._send_json(status, {"error": {"code": code, "message": message}})

    def do_POST(self):  # noqa: N802
        if not self._check_auth():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_error(400, -32700, f"Parse error: {e}")
            return

        method = payload.get("method", "")
        req_id = payload.get("id")
        params = payload.get("params", {}) or {}

        if req_id is None and method.startswith("notifications/"):
            self.send_response(202)
            self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
            self.end_headers()
            return

        if method == "initialize":
            session_id = f"gh-mock-{os.getpid()}-{int(time.time()*1000)}"
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "serverInfo": GITHUB_MOCK_SERVER_INFO,
                        "capabilities": {"tools": {}},
                    },
                },
                session_id=session_id,
            )
            return
        if method == "ping":
            self._send_json(200, {"jsonrpc": "2.0", "id": req_id, "result": {}})
            return
        if method == "tools/list":
            self._send_json(
                200,
                {"jsonrpc": "2.0", "id": req_id, "result": _gh_tools_list()},
            )
            return
        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {}) or {}
            result = _gh_tools_call(tool_name, arguments)
            if "error" in result:
                self._send_json(
                    200,
                    {"jsonrpc": "2.0", "id": req_id, "error": result["error"]},
                )
                return
            self._send_json(
                200,
                {"jsonrpc": "2.0", "id": req_id, "result": result},
            )
            return
        self._send_json(
            200,
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            },
        )

    def do_GET(self):  # noqa: N802
        # SSE 长连接 — 立即返 keep-alive 注释后关闭(mock 用)
        if not self._check_auth():
            return
        session_id = self.headers.get("Mcp-Session-Id")
        if not session_id:
            self._send_error(400, -32000, "Missing Mcp-Session-Id")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except Exception:
            pass

    def do_DELETE(self):  # noqa: N802
        session_id = self.headers.get("Mcp-Session-Id")
        self.send_response(204 if session_id else 404)
        self.end_headers()


class _GitHubMockServer:
    """在子线程跑 GitHub-like mock MCP server"""

    def __init__(self, port: int):
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), _GitHubMCPHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        # 等 server 起来
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                urllib.request.urlopen(
                    urllib.request.Request(f"http://127.0.0.1:{self.port}/mcp", method="GET"),
                    timeout=1,
                )
                return
            except urllib.error.HTTPError:
                return  # 401/400 都算活
            except Exception:
                time.sleep(0.1)
        raise RuntimeError(f"GitHub mock server 未起来 on port {self.port}")

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        self._server = None


# ============ 单元测试:直接连 mock GitHub server ============

def test_client_connects_to_github_mock_with_bearer():
    """StreamableHTTPClient 连 GitHub mock server,带 Authorization: Bearer ${GITHUB_TOKEN}"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="github",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": "Bearer ghp_fake_token_for_test"},
            connect_timeout_s=5.0,
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect(), f"connect 应成功, error={client.error}"
            assert client.connected
            assert client.session_id, "应有 session id"
            server_info = client._server_info.get("serverInfo", {})
            assert server_info.get("name") == "github-mcp-mock"
        finally:
            client.disconnect()
    finally:
        server.stop()
    print("✅ test_client_connects_to_github_mock_with_bearer PASSED")


def test_client_lists_github_tools():
    """列出 GitHub MCP 工具(模拟真实 github-mcp-server 接口)"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="github",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": "Bearer ghp_test"},
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            tools = client.list_tools()
            assert len(tools) == 3, f"应有 3 tools, 实际 {len(tools)}"
            names = {t.name for t in tools}
            assert names == {"list_repos", "create_issue", "get_file_contents"}
            # 每个 tool 都应有 schema
            for t in tools:
                assert t.input_schema.get("type") == "object"
                assert "properties" in t.input_schema
            # server_name 应被填充
            assert all(t.server_name == "github" for t in tools)
        finally:
            client.disconnect()
    finally:
        server.stop()
    print("✅ test_client_lists_github_tools PASSED")


def test_call_github_list_repos():
    """call_tool('list_repos') 返回模拟仓库"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="github",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": "Bearer ghp_test"},
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            result = client.call_tool("list_repos", {"visibility": "public", "limit": 10})
            assert result.get("success")
            content = result["content"]
            text = content["content"][0]["text"]
            data = json.loads(text)
            assert data["count"] == 2  # 2 public repos in mock
            assert all(r["visibility"] == "public" for r in data["repos"])
        finally:
            client.disconnect()
    finally:
        server.stop()
    print("✅ test_call_github_list_repos PASSED")


def test_call_github_create_issue():
    """call_tool('create_issue') 返回模拟 issue 对象"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="github",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": "Bearer ghp_test"},
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            result = client.call_tool(
                "create_issue",
                {
                    "owner": "green-agent",
                    "repo": "green-low-carbon-agent",
                    "title": "Add CCER calculator",
                    "body": "Need a tool for carbon credit estimation.",
                },
            )
            assert result.get("success"), result
            content = result["content"]
            text = content["content"][0]["text"]
            data = json.loads(text)
            assert data["number"] == 123
            assert "green-agent/green-low-carbon-agent" in data["html_url"]
            assert data["title"] == "Add CCER calculator"
        finally:
            client.disconnect()
    finally:
        server.stop()
    print("✅ test_call_github_create_issue PASSED")


def test_call_github_get_file_contents():
    """call_tool('get_file_contents') 返回模拟文件内容"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        cfg = StreamableHTTPClientConfig(
            name="github",
            url=f"http://127.0.0.1:{port}/mcp",
            headers={"Authorization": "Bearer ghp_test"},
            request_timeout_s=5.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        try:
            assert client.connect()
            result = client.call_tool(
                "get_file_contents",
                {"owner": "green-agent", "repo": "green-low-carbon-agent", "path": "README.md"},
            )
            assert result.get("success")
            text = result["content"]["content"][0]["text"]
            data = json.loads(text)
            assert data["path"] == "README.md"
            assert "README.md" in data["content"]
        finally:
            client.disconnect()
    finally:
        server.stop()
    print("✅ test_call_github_get_file_contents PASSED")


def test_missing_authorization_rejected():
    """无 Authorization 头时 server 应返 401(client 应感知失败)"""
    from mcp import StreamableHTTPClient, StreamableHTTPClientConfig

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        # 不带 Authorization — server 会 401
        cfg = StreamableHTTPClientConfig(
            name="github",
            url=f"http://127.0.0.1:{port}/mcp",
            # headers 为空
            request_timeout_s=3.0,
            connect_timeout_s=3.0,
            verify_ssl=False,
        )
        client = StreamableHTTPClient(cfg)
        ok = client.connect()
        assert not ok, "无 token 应连接失败"
        assert not client.connected
        assert client.error, "应有错误信息"
    finally:
        server.stop()
    print("✅ test_missing_authorization_rejected PASSED")


# ============ MCPRegistry 集成测试:mock server + 真实 yaml 加载 ============

def test_registry_loads_github_yaml_and_registers_tools():
    """MCPRegistry 加载 github-enabled yaml + 启动 mock server → tools 注册到本地"""
    from mcp import MCPRegistry

    port = _free_port()
    server = _GitHubMockServer(port)
    server.start()
    try:
        # 临时 yaml:启用 github,指向本地 mock
        yaml_text = textwrap.dedent(f"""
            mcp_servers:
              - name: github
                description: GitHub MCP for testing
                transport: streamable-http
                url: http://127.0.0.1:{port}/mcp
                headers:
                  Authorization: Bearer ${{GITHUB_TOKEN}}
                enabled: true
                connect_timeout_s: 5.0
                request_timeout_s: 5.0
        """).strip()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(yaml_text)
            path = f.name
        try:
            # 用真实 env var 注入(避免 placeholder 未展开)
            os.environ["GITHUB_TOKEN"] = "ghp_integration_test_token"
            try:
                reg = MCPRegistry()
                configs = reg.load_config(path)
                assert len(configs) == 1
                assert configs[0].headers["Authorization"] == "Bearer ghp_integration_test_token"

                # 跑 connect_all_async
                asyncio.run(reg.connect_all_async(configs))
                status = reg.status()
                assert status["servers_count"] == 1
                srv = status["servers"][0]
                assert srv["name"] == "github"
                assert srv["status"] == "connected", f"应 connected, 实际 {srv}"
                assert srv["tools_count"] == 3

                # 校验工具已注册到本地 ToolRegistry
                from agent.tools import get_registry as get_tool_registry

                tool_reg = get_tool_registry()
                mcp_tools = [n for n in tool_reg.list_all() if n.startswith("mcp_github_")]
                assert len(mcp_tools) == 3, f"应有 3 个 mcp_github_* 工具, 实际 {mcp_tools}"
                # list_repos / create_issue / get_file_contents 都应出现
                names = {n.replace("mcp_github_", "") for n in mcp_tools}
                assert names == {"list_repos", "create_issue", "get_file_contents"}

                # 通过本地 ToolRegistry 实际执行 list_repos
                adapter = tool_reg.get("mcp_github_list_repos")
                assert adapter is not None
                execution = adapter.execute(visibility="public", limit=5)
                assert execution.success, f"execute 应成功, error={execution.error}"
                assert "green-low-carbon-agent" in execution.data["text"]

                reg.shutdown()
            finally:
                # 清理临时 env(不影响真实 GITHUB_TOKEN)
                if "GITHUB_TOKEN" in os.environ and os.environ["GITHUB_TOKEN"] == "ghp_integration_test_token":
                    del os.environ["GITHUB_TOKEN"]
        finally:
            os.unlink(path)
    finally:
        server.stop()
    print("✅ test_registry_loads_github_yaml_and_registers_tools PASSED")


def test_registry_github_disabled_does_not_connect():
    """github enabled=false 时,MCPRegistry 不应连接(server 死了也不会 fail)"""
    from mcp import MCPRegistry

    # 用一个肯定连不上的端口(假设无 server 在跑)
    yaml_text = textwrap.dedent("""
        mcp_servers:
          - name: github
            transport: streamable-http
            url: http://127.0.0.1:1/mcp
            headers:
              Authorization: Bearer dummy
            enabled: false
    """).strip()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
        f.write(yaml_text)
        path = f.name
    try:
        reg = MCPRegistry()
        configs = reg.load_config(path)
        cfg = configs[0]
        assert cfg.enabled is False
        # 不跑 connect_all_async(否则会尝试连 port=1)
        # 仅校验 status 字段不变(默认 'connecting')
        status = reg.status()
        # connect_all_async 没跑过,servers_count 应为 0
        assert status["servers_count"] == 0
    finally:
        os.unlink(path)
    print("✅ test_registry_github_disabled_does_not_connect PASSED")


if __name__ == "__main__":
    test_client_connects_to_github_mock_with_bearer()
    test_client_lists_github_tools()
    test_call_github_list_repos()
    test_call_github_create_issue()
    test_call_github_get_file_contents()
    test_missing_authorization_rejected()
    test_registry_loads_github_yaml_and_registers_tools()
    test_registry_github_disabled_does_not_connect()
    print("\n🎉 All P11.C GitHub MCP integration tests PASSED")