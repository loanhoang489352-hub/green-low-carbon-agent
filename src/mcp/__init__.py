"""
MCP (Model Context Protocol) 集成

P6.S.16: 为智能体添加 MCP 双向支持
- MCPClient: 连接外部 MCP server(stdio 传输, JSON-RPC 2.0)
- MCPServer: 把本地 tools 暴露为 MCP server
- MCPToolAdapter: 把远程 MCP tool 包装成本地 BaseTool

P10.B: 加 Streamable HTTP 传输(2025-11-25 规范,替代旧 SSE-only)
- StreamableHTTPClient: HTTP POST + SSE 长连接,支持 Origin / session / OAuth stub
- MCPRegistry 按 transport 字段自动分发

零外部依赖,纯 stdlib(asyncio + json + subprocess + threading),遵循 MCP 协议规范。
"""

from .client import MCPClient, MCPClientConfig, MCPServerInfo, MCPTool
from .streamable_client import (
    StreamableHTTPClient,
    StreamableHTTPClientConfig,
    StreamableHTTPServerInfo,
    validate_origin,
    PROTOCOL_VERSION,
)
from .adapter import MCPToolAdapter
from .server import MCPServer
from .registry import MCPRegistry, get_mcp_registry

__all__ = [
    # stdio
    "MCPClient",
    "MCPClientConfig",
    "MCPServerInfo",
    "MCPTool",
    # streamable-http (P10.B)
    "StreamableHTTPClient",
    "StreamableHTTPClientConfig",
    "StreamableHTTPServerInfo",
    "validate_origin",
    "PROTOCOL_VERSION",
    # 共享
    "MCPToolAdapter",
    "MCPServer",
    "MCPRegistry",
    "get_mcp_registry",
]