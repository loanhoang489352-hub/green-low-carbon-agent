"""
MCP Tool 适配器 — 把远程 MCP tool 包装成 BaseTool

让现有 ToolRegistry / SkillExecutor / chat_enhanced 等代码无需修改
就能调用 MCP server 上的工具。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

from agent.tools.base import BaseTool, ToolResult

from .client import MCPClient, MCPTool

_logger = logging.getLogger(__name__)


class MCPToolAdapter(BaseTool):
    """
    把 MCP 远端 tool 包装成 BaseTool

    on execute(),异步调用 MCPClient.call_tool(),同步等待结果
    """

    def __init__(self, mcp_tool: MCPTool, client: MCPClient):
        self._mcp_tool = mcp_tool
        self._client = client
        # name / description / parameters 来自 MCP tool

    @property
    def name(self) -> str:
        # 加 mcp_ 前缀避免与本地 tool 重名
        return f"mcp_{self._mcp_tool.server_name}_{self._mcp_tool.name}"

    @property
    def description(self) -> str:
        prefix = f"[MCP: {self._mcp_tool.server_name}] "
        return prefix + (self._mcp_tool.description or "")

    @property
    def parameters(self) -> List[Dict[str, Any]]:
        # MCP 的 inputSchema 是 JSON Schema,转换成 BaseTool 的 List[Dict] 形式
        schema = self._mcp_tool.input_schema or {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        params = []
        for pname, pdef in properties.items():
            params.append({
                "name": pname,
                "type": pdef.get("type", "string"),
                "description": pdef.get("description", ""),
                "required": pname in required,
            })
        return params

    def execute(self, **kwargs) -> ToolResult:
        """同步执行(供 ToolExecutor 兼容)P6.S.16: 直接调同步 call_tool"""
        import time
        start = time.time()
        try:
            result = self._client.call_tool(self._mcp_tool.name, kwargs)
            elapsed = time.time() - start
            if result.get("success"):
                content = result.get("content", {})
                text = self._extract_text(content)
                return ToolResult(
                    success=True,
                    data={"raw": content, "text": text, "server": self._mcp_tool.server_name},
                    execution_time=elapsed,
                )
            else:
                return ToolResult(
                    success=False,
                    error=result.get("error", "unknown error"),
                    execution_time=elapsed,
                )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)[:200]}",
                execution_time=time.time() - start,
            )

    @staticmethod
    def _extract_text(content: Any) -> str:
        """从 MCP content 提取可读文本"""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            # MCP 标准: content = {"content": [{"type": "text", "text": "..."}]}
            items = content.get("content")
            if isinstance(items, list):
                parts = []
                for it in items:
                    if isinstance(it, dict):
                        if it.get("type") == "text":
                            parts.append(it.get("text", ""))
                        else:
                            parts.append(str(it))
                return "\n".join(parts)
            # 兜底
            return json_dumps(content)
        if isinstance(content, list):
            parts = []
            for it in content:
                if isinstance(it, dict) and it.get("type") == "text":
                    parts.append(it.get("text", ""))
                else:
                    parts.append(str(it))
            return "\n".join(parts)
        return str(content)


def json_dumps(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)
