"""
MCP (Model Context Protocol) 集成

P6.S.16: 为智能体添加 MCP 双向支持
- MCPClient: 连接外部 MCP server(stdio 传输, JSON-RPC 2.0)
- MCPServer: 把本地 tools 暴露为 MCP server
- MCPToolAdapter: 把远程 MCP tool 包装成本地 BaseTool

零外部依赖,纯 stdlib(asyncio + json + subprocess),遵循 MCP 协议规范。
"""
from .client import MCPClient, MCPClientConfig, MCPServerInfo, MCPTool
from .adapter import MCPToolAdapter
from .server import MCPServer
from .registry import MCPRegistry, get_mcp_registry

__all__ = [
    "MCPClient",
    "MCPClientConfig",
    "MCPServerInfo",
    "MCPTool",
    "MCPToolAdapter",
    "MCPServer",
    "MCPRegistry",
    "get_mcp_registry",
]
