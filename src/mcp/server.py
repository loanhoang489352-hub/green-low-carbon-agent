"""
MCP Server — 把本地 ToolRegistry 暴露为 MCP server

支持方法:
  - initialize       握手,返 server info
  - tools/list       列出本地 tools
  - tools/call       调用本地 tool

通信: JSON-RPC 2.0 over stdio(每行一个 JSON)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Dict, List, Optional

from agent.tools.base import BaseTool, ToolResult
from agent.tools.registry import ToolRegistry

_logger = logging.getLogger(__name__)


class MCPServer:
    """
    MCP Server,接受 stdio 上的 JSON-RPC 请求,调度到本地 ToolRegistry

    用法:
        server = MCPServer(tool_registry, server_name="green-agent")
        await server.run()  # 启动 stdio 循环(永久阻塞)
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        server_name: str = "green-low-carbon-agent",
        server_version: str = "2.0",
    ):
        self.tool_registry = tool_registry
        self.server_name = server_name
        self.server_version = server_version

    async def run(self) -> None:
        """永久循环,从 stdin 读 JSON-RPC,处理后写回 stdout"""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        # 写 stdout 用普通 write(不阻塞)
        write_transport, write_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, sys.stdout
        )
        writer = asyncio.StreamWriter(write_transport, write_protocol, None, loop)
        _logger.info("[MCPServer] 启动, 等待 JSON-RPC 请求...")

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                try:
                    request = json.loads(text)
                except Exception as e:
                    err = self._error_response(None, -32700, f"Parse error: {e}")
                    writer.write((json.dumps(err) + "\n").encode("utf-8"))
                    await writer.drain()
                    continue
                # 处理
                response = await self._handle(request)
                if response is not None:
                    writer.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
                    await writer.drain()
            except Exception as e:
                _logger.warning("[MCPServer] loop 异常: %s", e)
                break

    async def _handle(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """处理单个 JSON-RPC 请求(通知返 None)"""
        method = request.get("method", "")
        req_id = request.get("id")
        params = request.get("params", {})

        # 通知(无 id):不返响应
        if req_id is None and method.startswith("notifications/"):
            _logger.debug("[MCPServer] 通知: %s", method)
            return None

        try:
            if method == "initialize":
                return self._result(
                    req_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": self.server_name,
                            "version": self.server_version,
                        },
                        "capabilities": {"tools": {}},
                    },
                )
            elif method == "tools/list":
                return self._result(req_id, {"tools": self._list_tools()})
            elif method == "tools/call":
                return await self._call_tool(req_id, params)
            elif method == "ping":
                return self._result(req_id, {})
            else:
                return self._error_response(req_id, -32601, f"Method not found: {method}")
        except Exception as e:
            return self._error_response(req_id, -32603, f"Internal error: {e}")

    def _list_tools(self) -> List[Dict[str, Any]]:
        tools_out = []
        for name in self.tool_registry.list_all():
            inst = self.tool_registry.get(name)
            if not inst:
                continue
            meta = self.tool_registry.get_metadata(name)
            desc = (meta.description if meta else None) or inst.description or ""
            tools_out.append(
                {
                    "name": name,
                    "description": desc,
                    "inputSchema": self._params_to_schema(inst),
                }
            )
        return tools_out

    @staticmethod
    def _params_to_schema(tool: BaseTool) -> Dict[str, Any]:
        """把 BaseTool 的 List[Dict] parameters 转为 JSON Schema"""
        try:
            params = tool.parameters
        except Exception:
            return {"type": "object", "properties": {}}
        properties = {}
        required = []
        for p in params or []:
            pname = p.get("name")
            if not pname:
                continue
            ptype = p.get("type", "string")
            ptype_map = {
                "string": "string",
                "int": "integer",
                "integer": "integer",
                "float": "number",
                "number": "number",
                "bool": "boolean",
                "boolean": "boolean",
                "list": "array",
                "array": "array",
                "dict": "object",
                "object": "object",
            }
            js_type = ptype_map.get(ptype, "string")
            properties[pname] = {
                "type": js_type,
                "description": p.get("description", ""),
            }
            if p.get("required"):
                required.append(pname)
        schema = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    async def _call_tool(self, req_id, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        inst = self.tool_registry.get(name)
        if not inst:
            return self._error_response(req_id, -32602, f"Tool not found: {name}")
        try:
            # 同步 execute 在线程池跑,避免阻塞 event loop
            loop = asyncio.get_event_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(inst.execute, **arguments)
                result: ToolResult = fut.result(timeout=60)
            if result.success:
                data = result.data
                # 把 data 转成 MCP content 形式
                if isinstance(data, dict):
                    text = data.get("text") or json.dumps(data, ensure_ascii=False)
                else:
                    text = str(data)
                return self._result(
                    req_id,
                    {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    },
                )
            else:
                return self._result(
                    req_id,
                    {
                        "content": [{"type": "text", "text": f"Error: {result.error}"}],
                        "isError": True,
                    },
                )
        except Exception as e:
            return self._error_response(req_id, -32603, f"Tool execution failed: {e}")

    @staticmethod
    def _result(req_id, result):
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error_response(req_id, code: int, message: str):
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


def run_mcp_server_sync():
    """同步入口(供 subprocess 启动)"""
    from agent.tools import get_registry as get_tool_registry

    reg = get_tool_registry()
    server = MCPServer(reg, server_name="green-low-carbon-agent")
    asyncio.run(server.run())


if __name__ == "__main__":
    # 允许 python -m mcp.server 直接启动
    run_mcp_server_sync()
