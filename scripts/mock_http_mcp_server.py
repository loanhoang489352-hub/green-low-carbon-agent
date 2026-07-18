"""
Mock HTTP MCP Server — 实现 MCP 2025-11-25 Streamable HTTP 传输

启动:  python scripts/mock_http_mcp_server.py [--port 8765]

端点(默认 http://127.0.0.1:8765/mcp):
  POST /mcp    客户端→服务端 JSON-RPC 请求
  GET  /mcp    服务端→客户端 主动通知(SSE 长连接)
  DELETE /mcp  终止会话

提供 3 个示例 tool(与 stdio mock 一致,便于跨 transport 测试):
  - mock_echo:    回显文本
  - mock_weather: 固定天气数据
  - mock_carbon:  简单碳排放计算

P10.B: 仅依赖 stdlib(http.server),可作 e2e fixture。
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

PROTOCOL_VERSION = "2025-11-25"
SERVER_INFO = {"name": "mock-http-mcp-server", "version": "1.0.0"}
ALLOWED_ORIGINS = {"https://green-low-carbon-agent.local", "http://localhost", None}

# 会话存储(session_id -> {created_at})
_sessions: Dict[str, Dict[str, Any]] = {}
_sessions_lock = threading.Lock()


def _tools_list() -> Dict[str, Any]:
    """返回 tools/list 响应体"""
    return {
        "tools": [
            {
                "name": "mock_echo",
                "description": "回显输入的文本(用于测试 MCP Streamable HTTP)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "要回显的文本"}},
                    "required": ["text"],
                },
            },
            {
                "name": "mock_weather",
                "description": "返回模拟天气数据(Streamable HTTP 测试用)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"city": {"type": "string", "description": "城市名"}},
                    "required": ["city"],
                },
            },
            {
                "name": "mock_carbon",
                "description": "计算简单碳排放(距离 × 系数)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "distance_km": {"type": "number", "description": "距离(km)"},
                        "mode": {"type": "string", "description": "car/bus/cycling/walking"},
                    },
                    "required": ["distance_km"],
                },
            },
        ]
    }


def _tools_call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """tools/call 业务逻辑"""
    if name == "mock_echo":
        text = arguments.get("text", "")
        content = f"echo: {text}"
    elif name == "mock_weather":
        city = arguments.get("city", "未知")
        content = json.dumps(
            {"city": city, "temp_c": 22, "description": "多云", "humidity": 60, "wind": "东南风 3级"},
            ensure_ascii=False,
        )
    elif name == "mock_carbon":
        try:
            distance = float(arguments.get("distance_km", 0))
        except (ValueError, TypeError):
            distance = 0.0
        mode = arguments.get("mode", "car")
        factors = {"car": 0.21, "bus": 0.08, "cycling": 0, "walking": 0, "transit": 0.05}
        factor = factors.get(mode, 0.21)
        carbon = round(distance * factor, 3)
        content = json.dumps(
            {"distance_km": distance, "mode": mode, "factor_kg_per_km": factor, "carbon_kg": carbon},
            ensure_ascii=False,
        )
    else:
        return {"error": {"code": -32602, "message": f"Tool not found: {name}"}}
    return {"content": [{"type": "text", "text": content}], "isError": False}


def _handle_request(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """处理单个 JSON-RPC 请求,通知返 None"""
    method = payload.get("method", "")
    req_id = payload.get("id")
    params = payload.get("params", {}) or {}

    if req_id is None and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": _tools_list()}
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        result = _tools_call(name, arguments)
        if "error" in result:
            return {"jsonrpc": "2.0", "id": req_id, "error": result["error"]}
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP 请求处理器"""

    def log_message(self, fmt: str, *args: Any) -> None:
        # 重定向到 stderr,避免污染测试输出
        sys.stderr.write("[mock-http-mcp] " + (fmt % args) + "\n")
        sys.stderr.flush()

    # ---- 工具方法 ----

    def _check_origin(self) -> bool:
        """校验 Origin(GFW 安全)"""
        origin = self.headers.get("Origin")
        # 接受空 Origin(server-to-server);否则必须命中白名单
        if origin is None:
            return True
        return origin in ALLOWED_ORIGINS

    def _send_json(self, status: int, body: Dict[str, Any], session_id: Optional[str] = None) -> None:
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

    # ---- HTTP 方法 ----

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_origin():
            self._send_error(403, -32000, "Origin not allowed")
            return
        # 读 body
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as e:
            self._send_error(400, -32700, f"Parse error: {e}")
            return
        # 处理
        try:
            response = _handle_request(payload)
        except Exception as e:
            self._send_error(500, -32603, f"Internal error: {e}")
            return
        # 通知:返 202 Accepted(无 body)
        if response is None:
            self.send_response(202)
            self.send_header("MCP-Protocol-Version", PROTOCOL_VERSION)
            self.end_headers()
            return
        # initialize 响应:下发 session id
        session_id: Optional[str] = None
        if payload.get("method") == "initialize" and "result" in response:
            session_id = uuid.uuid4().hex
            with _sessions_lock:
                _sessions[session_id] = {"created_at": __import__("time").time()}
        self._send_json(200, response, session_id=session_id)

    def do_GET(self) -> None:  # noqa: N802
        """GET:服务端→客户端 SSE 长连接(返回 keep-alive 注释 + 立即关闭,简化为快速关闭)"""
        if not self._check_origin():
            self._send_error(403, -32000, "Origin not allowed")
            return
        session_id = self.headers.get("Mcp-Session-Id")
        if not session_id or session_id not in _sessions:
            self._send_error(400, -32000, "Missing or invalid Mcp-Session-Id")
            return
        # 简化为:发一个 open 注释,然后立即关闭
        # 真实 server 会保持长连接持续推送 notification
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

    def do_DELETE(self) -> None:  # noqa: N802
        """DELETE:终止会话"""
        session_id = self.headers.get("Mcp-Session-Id")
        if session_id and session_id in _sessions:
            with _sessions_lock:
                _sessions.pop(session_id, None)
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.end_headers()


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Mock Streamable HTTP MCP Server")
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), MCPHTTPHandler)
    sys.stderr.write(
        f"[mock-http-mcp] listening on http://{args.host}:{args.port}/mcp\n"
    )
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())