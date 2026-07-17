"""
MCP Registry — 集中管理所有 MCP client + 状态

启动时根据配置连接外部 MCP server,把它们的 tool 注册到本地 ToolRegistry
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from agent.tools import get_registry as get_tool_registry
from agent.tools.base import ToolMetadata

from .adapter import MCPToolAdapter
from .client import MCPClient, MCPClientConfig, MCPServerInfo, MCPTool, parse_command_string

_logger = logging.getLogger(__name__)

_mcp_registry: Optional["MCPRegistry"] = None


class MCPRegistry:
    """
    MCP client 集中管理

    - load_config(): 从 config/mcp_servers.yaml 读配置
    - connect_all(): 启动所有启用的 client,后台 task 跑 read_loop
    - 注册每个 client 的 tool 到本地 ToolRegistry
    - 提供状态查询(给 /api/mcp/status 用)
    """

    def __init__(self):
        self._clients: Dict[str, MCPClient] = {}
        self._server_info: Dict[str, MCPServerInfo] = {}
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

    def load_config(self, config_path: str = "config/mcp_servers.yaml") -> List[MCPClientConfig]:
        """从 YAML 读 MCP server 配置"""
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
        # P6.S.16: 解析 project_root(server 启动时 cwd 是 src/,相对路径会失败)
        config_dir = path.resolve().parent
        project_root = config_dir.parent if config_dir.name == "config" else config_dir
        configs = []
        for s in data.get("mcp_servers", []) or []:
            try:
                # 支持 "command: python -m foo --bar" 单字符串形式
                cmd = s.get("command", "")
                if isinstance(cmd, str) and " " in cmd and not s.get("args"):
                    parts = parse_command_string(cmd)
                    command, args = parts[0], parts[1:]
                else:
                    command = cmd
                    args = s.get("args", []) or []
                # P6.S.16: 相对路径的 args 转成绝对路径(基于 project_root)
                resolved_args = []
                for a in args:
                    if a.startswith("scripts/") or a.startswith("scripts\\"):
                        resolved_args.append(str(project_root / a))
                    else:
                        resolved_args.append(a)
                cfg = MCPClientConfig(
                    name=s.get("name", f"mcp_{len(configs)}"),
                    command=command,
                    args=resolved_args,
                    env=s.get("env", {}) or {},
                    cwd=s.get("cwd") or str(project_root),  # 默认 cwd = project_root
                    description=s.get("description", ""),
                    enabled=s.get("enabled", True),
                    connect_timeout_s=float(s.get("connect_timeout_s", 10.0)),
                    request_timeout_s=float(s.get("request_timeout_s", 30.0)),
                )
                configs.append(cfg)
            except Exception as e:
                _logger.warning("[MCPRegistry] config 一条解析失败: %s", e)
        _logger.info("[MCPRegistry] 加载配置: %d 个 MCP server", len(configs))
        return configs

    async def connect_all_async(self, configs: List[MCPClientConfig]) -> None:
        """P6.S.16: 同步连接(已非 async,保留 async 入口以兼容)"""
        for cfg in configs:
            client = MCPClient(cfg)
            self._clients[cfg.name] = client
            self._server_info[cfg.name] = MCPServerInfo(
                name=cfg.name,
                status="connecting",
                command=f"{cfg.command} {' '.join(cfg.args)}".strip(),
            )
            try:
                # P6.S.16: MCPClient.connect() 现在是同步的
                ok = client.connect()
                if ok:
                    self._server_info[cfg.name].status = "connected"
                    self._server_info[cfg.name].connected_at = client._connected_at
                    self._server_info[cfg.name].server_info = client._server_info
                    # 拉 tool 列表
                    tools = client.list_tools()
                    self._server_info[cfg.name].tools_count = len(tools)
                    for t in tools:
                        self._tools[f"{cfg.name}::{t.name}"] = t
                    # 注册到本地 ToolRegistry
                    self._register_tools(tools)
                else:
                    self._server_info[cfg.name].status = "error"
                    self._server_info[cfg.name].error = client.error
            except Exception as e:
                self._server_info[cfg.name].status = "error"
                self._server_info[cfg.name].error = f"{type(e).__name__}: {str(e)[:200]}"

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

        server 启动时调一次,非阻塞主进程。
        """
        if self._started:
            return
        configs = self.load_config(config_path)
        if not configs:
            return

        def _thread_main():
            _logger.info("[MCPRegistry] 后台线程启动,准备连接 %d servers", len(configs))
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self.connect_all_async(configs))
                _logger.info("[MCPRegistry] connect_all_async 完成,进入 run_forever 保持 read_loop")
                # 不退出 loop(让 read_loop 持续跑)
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
                "connected" in statuses or all(s in ("error", "disabled") for s in statuses)
            ):
                break
            time.sleep(0.2)

    def shutdown(self) -> None:
        """关闭所有 client"""
        for name, client in list(self._clients.items()):
            try:
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
            servers.append(
                {
                    "name": name,
                    "status": info.status,
                    "command": info.command,
                    "tools_count": info.tools_count,
                    "error": info.error,
                    "connected_at": info.connected_at,
                    "server_info": info.server_info,
                }
            )
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
