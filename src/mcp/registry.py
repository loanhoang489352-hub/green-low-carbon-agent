"""
MCP Registry — 集中管理所有 MCP client + 状态

启动时根据配置连接外部 MCP server,把它们的 tool 注册到本地 ToolRegistry

P10.B: 支持两种 transport 分发
  - stdio:           现有 MCPClient(子进程 + JSON-RPC over stdin/stdout)
  - streamable-http: 新增 StreamableHTTPClient(HTTP POST + SSE, 2025-11-25 规范)
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml

from agent.tools import get_registry as get_tool_registry
from agent.tools.base import ToolMetadata

from .adapter import MCPToolAdapter
from .client import MCPClient, MCPClientConfig, MCPServerInfo, MCPTool, parse_command_string
from .streamable_client import (
    StreamableHTTPClient,
    StreamableHTTPClientConfig,
    StreamableHTTPServerInfo,
)

_logger = logging.getLogger(__name__)

_mcp_registry: Optional["MCPRegistry"] = None

# 统一 server 信息类型(stdio / http 都有 name/status/error/...)
TransportInfo = Union[MCPServerInfo, StreamableHTTPServerInfo]


def _make_server_info(name: str, transport: str, descriptor: str) -> TransportInfo:
    """根据 transport 创建对应类型的状态对象"""
    if transport == "streamable-http":
        return StreamableHTTPServerInfo(name=name, status="connecting", url=descriptor)
    return MCPServerInfo(name=name, status="connecting", command=descriptor)


class MCPRegistry:
    """
    MCP client 集中管理

    - load_config(): 从 config/mcp_servers.yaml 读配置(transport 字段分发)
    - connect_all(): 启动所有启用的 client,后台 task 跑 read_loop / SSE
    - 注册每个 client 的 tool 到本地 ToolRegistry
    - 提供状态查询(给 /api/mcp/status 用)
    """

    def __init__(self):
        # 客户端实例(stdio 用 MCPClient,http 用 StreamableHTTPClient)
        self._clients: Dict[str, Union[MCPClient, StreamableHTTPClient]] = {}
        self._client_kinds: Dict[str, str] = {}  # name -> "stdio" | "streamable-http"
        self._server_info: Dict[str, TransportInfo] = {}
        self._tools: Dict[str, MCPTool] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._read_tasks: Dict[str, asyncio.Task] = {}
        self._config_path: Optional[Path] = None
        self._started = False

    @staticmethod
    def instance() -> "MCPRegistry":
        global _mcp_registry
        if _mcp_registry is None:
            _mcp_registry = MCPRegistry()
        return _mcp_registry

    def load_config(self, config_path: str = "config/mcp_servers.yaml") -> List[Union[MCPClientConfig, StreamableHTTPClientConfig]]:
        """
        从 YAML 读 MCP server 配置
        按 transport 字段返回对应类型的 config(stdio / streamable-http)
        """
        path = Path(config_path)
        if not path.exists():
            _logger.info("[MCPRegistry] config 文件不存在: %s (跳过 MCP 启动)", path)
            return []
        self._config_path = path
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            _logger.warning("[MCPRegistry] config 解析失败: %s", e)
            return []
        # 解析 project_root(server 启动时 cwd 是 src/,相对路径会失败)
        config_dir = path.resolve().parent
        project_root = config_dir.parent if config_dir.name == "config" else config_dir
        configs: List[Union[MCPClientConfig, StreamableHTTPClientConfig]] = []
        servers_raw = data.get("mcp_servers", []) or []
        # P10.B: 也支持 servers 字段(任务示例 yaml 用此名,兼容两种)
        if not servers_raw and isinstance(data.get("servers"), list):
            servers_raw = data.get("servers")
        for s in servers_raw:
            try:
                transport = (s.get("transport") or "stdio").strip().lower()
                if transport == "streamable-http":
                    cfg = self._parse_http_config(s)
                elif transport == "stdio":
                    cfg = self._parse_stdio_config(s, project_root)
                else:
                    _logger.warning(
                        "[MCPRegistry] 未知 transport: %s (server=%s, 跳过)",
                        transport,
                        s.get("name", "?"),
                    )
                    continue
                configs.append(cfg)
            except Exception as e:
                _logger.warning("[MCPRegistry] config 一条解析失败: %s", e)
        _logger.info(
            "[MCPRegistry] 加载配置: %d 个 MCP server (%s)",
            len(configs),
            self._summarize_transports(configs),
        )
        return configs

    @staticmethod
    def _parse_stdio_config(s: Dict, project_root: Path) -> MCPClientConfig:
        """解析 stdio transport 配置"""
        # 支持 "command: python -m foo --bar" 单字符串形式
        cmd = s.get("command", "")
        if isinstance(cmd, str) and " " in cmd and not s.get("args"):
            parts = parse_command_string(cmd)
            command, args = parts[0], parts[1:]
        else:
            command = cmd
            args = s.get("args", []) or []
        # 相对路径的 args 转成绝对路径(基于 project_root)
        resolved_args = []
        for a in args:
            if a.startswith("scripts/") or a.startswith("scripts\\"):
                resolved_args.append(str(project_root / a))
            else:
                resolved_args.append(a)
        return MCPClientConfig(
            name=s.get("name", f"mcp_{len(project_root.name)}"),
            command=command,
            args=resolved_args,
            env=s.get("env", {}) or {},
            cwd=s.get("cwd") or str(project_root),
            description=s.get("description", ""),
            enabled=s.get("enabled", True),
            connect_timeout_s=float(s.get("connect_timeout_s", 10.0)),
            request_timeout_s=float(s.get("request_timeout_s", 30.0)),
        )

    @staticmethod
    def _parse_http_config(s: Dict) -> StreamableHTTPClientConfig:
        """解析 streamable-http transport 配置"""
        from .streamable_client import build_streamable_http_config_from_yaml

        d = dict(s)
        d.setdefault("transport", "streamable-http")
        return build_streamable_http_config_from_yaml(d)

    @staticmethod
    def _summarize_transports(configs: List) -> str:
        counts: Dict[str, int] = {}
        for c in configs:
            t = getattr(c, "transport", "stdio")
            counts[t] = counts.get(t, 0) + 1
        return ", ".join(f"{k}={v}" for k, v in counts.items()) or "none"

    def _instantiate_client(self, cfg: Union[MCPClientConfig, StreamableHTTPClientConfig]):
        """根据 config 类型构造 client 实例"""
        if isinstance(cfg, StreamableHTTPClientConfig):
            return StreamableHTTPClient(cfg), "streamable-http"
        return MCPClient(cfg), "stdio"

    async def connect_all_async(self, configs: List) -> None:
        """连接所有 MCP server(同步 client 内部,本入口保留 async 兼容)"""
        for cfg in configs:
            client, kind = self._instantiate_client(cfg)
            self._clients[cfg.name] = client
            self._client_kinds[cfg.name] = kind
            descriptor = getattr(cfg, "url", None) or f"{cfg.command} {' '.join(cfg.args)}".strip()
            self._server_info[cfg.name] = _make_server_info(cfg.name, kind, descriptor)
            try:
                ok = client.connect()
                if ok:
                    self._on_connected(cfg.name, client)
                else:
                    self._server_info[cfg.name].status = "error"
                    self._server_info[cfg.name].error = getattr(client, "error", "unknown")
            except Exception as e:
                self._server_info[cfg.name].status = "error"
                self._server_info[cfg.name].error = (
                    f"{type(e).__name__}: {str(e)[:200]}"
                )

    def _on_connected(self, name: str, client) -> None:
        """连接成功后:更新状态 + 拉 tools + 注册到本地 ToolRegistry"""
        info = self._server_info[name]
        info.status = "connected"
        # 两种 client 都有 _connected_at 和 _server_info 属性
        info.connected_at = getattr(client, "_connected_at", None)
        info.server_info = getattr(client, "_server_info", None)
        if isinstance(info, StreamableHTTPServerInfo):
            info.session_id = getattr(client, "_session_id", None)
        try:
            tools = client.list_tools()
        except Exception as e:
            _logger.warning("[MCPRegistry] %s list_tools 失败: %s", name, e)
            tools = []
        info.tools_count = len(tools)
        for t in tools:
            self._tools[f"{name}::{t.name}"] = t
        self._register_tools(tools)

    def _register_tools(self, tools: List[MCPTool]) -> None:
        """把 MCP tools 注册到本地 ToolRegistry"""
        tool_reg = get_tool_registry()
        for t in tools:
            client = self._clients.get(t.server_name)
            if not client:
                continue
            try:
                adapter = MCPToolAdapter(t, client)
                meta = ToolMetadata(
                    name=adapter.name,
                    description=adapter.description,
                    category=f"mcp_{t.server_name}",
                    tags=["mcp", t.server_name],
                    version="1.0",
                )
                tool_reg.register(adapter, meta, overwrite=True)
                _logger.info(
                    "[MCPRegistry] 注册 MCP tool: %s (server=%s)",
                    adapter.name,
                    t.server_name,
                )
            except Exception as e:
                _logger.warning("[MCPRegistry] 注册 %s 失败: %s", t.name, e)

    def connect_all_blocking(self, config_path: str = "config/mcp_servers.yaml") -> None:
        """
        同步入口:在后台线程起 event loop,连接所有 MCP server
        """
        if self._started:
            return
        configs = self.load_config(config_path)
        if not configs:
            return

        def _thread_main():
            _logger.info(
                "[MCPRegistry] 后台线程启动,准备连接 %d servers", len(configs)
            )
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self.connect_all_async(configs))
                _logger.info("[MCPRegistry] connect_all_async 完成")
                # stdio 客户端需要 event loop 持续运行(read_loop 在后台跑)
                # http 客户端不需要,但统一保持
                if any(k == "stdio" for k in self._client_kinds.values()):
                    self._loop.run_forever()
            except Exception as e:
                _logger.warning("[MCPRegistry] 后台线程异常: %s", e, exc_info=True)
            finally:
                try:
                    self._loop.close()
                except Exception:
                    pass

        self._thread = threading.Thread(
            target=_thread_main,
            name="mcp-registry",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        # 等几秒让 connect 跑完
        import time

        deadline = time.time() + 8.0
        while time.time() < deadline:
            statuses = [info.status for info in self._server_info.values()]
            if statuses and (
                "connected" in statuses
                or all(s in ("error", "disabled") for s in statuses)
            ):
                break
            time.sleep(0.2)

    def shutdown(self) -> None:
        """关闭所有 client"""
        for name, client in list(self._clients.items()):
            try:
                # 两种 client 都有 disconnect / _cleanup
                if hasattr(client, "disconnect"):
                    client.disconnect()
                else:
                    client._cleanup()
            except Exception:
                pass
        self._clients.clear()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    def status(self) -> Dict:
        """返所有 server 状态(给 debug 端点用)"""
        servers = []
        for name, info in self._server_info.items():
            entry = {
                "name": name,
                "transport": self._client_kinds.get(name, "stdio"),
                "status": info.status,
                "tools_count": info.tools_count,
                "error": info.error,
                "connected_at": info.connected_at,
                "server_info": info.server_info,
            }
            # stdio: command; http: url
            if isinstance(info, StreamableHTTPServerInfo):
                entry["url"] = info.url
                entry["session_id"] = info.session_id
            else:
                entry["command"] = info.command
            servers.append(entry)
        tools = [
            {"key": k, "server": v.server_name, "name": v.name, "description": v.description}
            for k, v in self._tools.items()
        ]
        return {
            "servers_count": len(servers),
            "tools_count": len(tools),
            "servers": servers,
            "tools": tools,
            "config_path": str(self._config_path) if self._config_path else None,
        }


def get_mcp_registry() -> MCPRegistry:
    return MCPRegistry.instance()