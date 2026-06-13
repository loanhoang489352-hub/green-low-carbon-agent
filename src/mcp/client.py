"""
MCP 客户端 — 通过 stdio 传输连接外部 MCP server

协议: JSON-RPC 2.0 over stdio(每行一个 JSON)
支持方法:
  - initialize         握手
  - tools/list        列出可用工具
  - tools/call        调用工具
  - notifications/*   通知(无响应)

P6.S.16: 同步 I/O 线程实现(避免 asyncio + Windows pipe 兼容问题)
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shlex
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_logger = logging.getLogger(__name__)


@dataclass
class MCPClientConfig:
    """MCP 客户端配置(对应 config/mcp_servers.yaml 一条 server)"""
    name: str                                          # 内部唯一名
    command: str                                        # 启动命令(如 "python" / "node")
    args: List[str] = field(default_factory=list)       # 命令参数
    env: Dict[str, str] = field(default_factory=dict)   # 额外环境变量
    cwd: Optional[str] = None                           # 工作目录
    description: str = ""                               # 描述
    enabled: bool = True                                # 是否启用
    connect_timeout_s: float = 10.0                     # 启动超时
    request_timeout_s: float = 30.0                     # 单次请求超时


@dataclass
class MCPTool:
    """远程 MCP 工具描述"""
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPServerInfo:
    """MCP server 状态"""
    name: str
    status: str  # "connected" | "disconnected" | "error" | "disabled"
    command: str
    tools_count: int = 0
    error: Optional[str] = None
    connected_at: Optional[float] = None
    server_info: Optional[Dict[str, Any]] = None  # 握手返的 server info


class MCPClient:
    """
    MCP 客户端,异步连接外部 MCP server,管理 stdio 通信

    用法:
        config = MCPClientConfig(name="amap", command="python", args=["amap_mcp.py"])
        client = MCPClient(config)
        await client.connect()
        tools = await client.list_tools()
        result = await client.call_tool("geocode", {"address": "北京西单"})
        await client.disconnect()
    """

    def __init__(self, config: MCPClientConfig):
        self.config = config
        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._connected = False
        self._server_info: Optional[Dict[str, Any]] = None
        self._write_lock = threading.Lock()
        self._read_thread: Optional[threading.Thread] = None
        self._stop_read = threading.Event()
        self._response_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._connected_at: Optional[float] = None
        self._error: Optional[str] = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def error(self) -> Optional[str]:
        return self._error

    def connect(self) -> bool:
        """
        启动 MCP server 进程 + 握手(initialize)
        P6.S.16: 同步实现,非 async
        成功返 True,失败返 False(error 属性可查)
        """
        if not self.config.enabled:
            self._error = "disabled by config"
            return False
        try:
            # 1. 启动子进程(stdio)
            env = os.environ.copy()
            env.update(self.config.env)
            env.setdefault("PYTHONIOENCODING", "utf-8")
            env.setdefault("PYTHONUTF8", "1")
            cmd = [self.config.command] + self.config.args
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                cwd=self.config.cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,  # 行缓冲
            )
            # 2. 启动 read 后台线程(关键!否则响应回来没人接)
            self._stop_read.clear()
            self._read_thread = threading.Thread(
                target=self._read_loop_sync,
                name=f"mcp-read-{self.config.name}",
                daemon=True,
            )
            self._read_thread.start()
            time.sleep(0.1)  # 让 read 线程先进入循环
            # 3. 发送 initialize 请求
            result = self._request_sync(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "green-low-carbon-agent",
                        "version": "2.0",
                    },
                },
                timeout=self.config.connect_timeout_s,
            )
            if "error" in result:
                self._error = f"initialize error: {result['error']}"
                self._cleanup()
                return False
            self._server_info = result.get("result", {})
            # 4. 发送 initialized 通知
            self._notify_sync("notifications/initialized", {})
            self._connected = True
            self._connected_at = time.time()
            self._error = None
            _logger.info(
                "[MCPClient] %s 已连接: server=%s v%s",
                self.config.name,
                self._server_info.get("serverInfo", {}).get("name", "?"),
                self._server_info.get("serverInfo", {}).get("version", "?"),
            )
            return True
        except Exception as e:
            self._error = f"{type(e).__name__}: {str(e)[:200]}"
            self._cleanup()
            _logger.warning("[MCPClient] %s 连接失败: %s", self.config.name, self._error)
            return False

    def disconnect(self) -> None:
        """断开连接,清理子进程"""
        self._cleanup()

    def _cleanup(self) -> None:
        self._stop_read.set()
        if self._process:
            try:
                self._process.stdin.close()
            except Exception:
                pass
            try:
                self._process.terminate()
            except Exception:
                pass
            try:
                self._process.wait(timeout=2)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        self._connected = False
        self._server_info = None

    def list_tools(self) -> List[MCPTool]:
        """列出 server 提供的所有 tool(同步)"""
        if not self._connected:
            return []
        try:
            result = self._request_sync("tools/list", {})
            if "error" in result:
                _logger.warning(
                    "[MCPClient] %s list_tools 错误: %s",
                    self.config.name, result["error"],
                )
                return []
            tools_raw = result.get("result", {}).get("tools", [])
            return [
                MCPTool(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self.config.name,
                )
                for t in tools_raw
            ]
        except Exception as e:
            _logger.warning("[MCPClient] %s list_tools 异常: %s", self.config.name, e)
            return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用远程 tool(同步)"""
        if not self._connected:
            return {"success": False, "error": "client not connected"}
        try:
            result = self._request_sync(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
                timeout=self.config.request_timeout_s,
            )
            if "error" in result:
                return {"success": False, "error": str(result["error"])[:500]}
            return {"success": True, "content": result.get("result", {})}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    # ============ 底层 JSON-RPC 通信(同步) ============

    def _request_sync(self, method: str, params: Dict[str, Any], timeout: float = 30.0) -> Dict[str, Any]:
        """发送 JSON-RPC 请求,同步等响应"""
        if not self._process or self._process.stdin is None:
            return {"error": "process not running"}
        self._request_id += 1
        request_id = self._request_id
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        try:
            line = json.dumps(message, ensure_ascii=False) + "\n"
        except Exception as e:
            return {"error": f"encode failed: {e}"}

        with self._write_lock:
            try:
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except Exception as e:
                stderr_msg = ""
                try:
                    if self._process and self._process.stderr:
                        stderr_msg = self._process.stderr.read(500) or ""
                except Exception:
                    pass
                return {"error": f"write failed: {e} | stderr: {stderr_msg[:200]}"}

        # 等响应(从 _response_queue 阻塞取)
        try:
            resp = self._response_queue.get(timeout=timeout)
            return resp
        except Exception:
            return {"error": f"timeout after {timeout}s"}

    def _notify_sync(self, method: str, params: Dict[str, Any]) -> None:
        """发送 JSON-RPC 通知(无响应)"""
        if not self._process or self._process.stdin is None:
            return
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        with self._write_lock:
            try:
                line = json.dumps(message, ensure_ascii=False) + "\n"
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except Exception:
                pass

    def _read_loop_sync(self) -> None:
        """
        后台线程读循环(同步 I/O)
        持续从 server stdout 读 JSON-RPC 响应,塞到 _response_queue
        """
        if not self._process or self._process.stdout is None:
            return
        try:
            while not self._stop_read.is_set() and self._process and self._process.stdout:
                try:
                    line = self._process.stdout.readline()
                except Exception:
                    break
                if not line:
                    break
                if isinstance(line, bytes):
                    try:
                        line = line.decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                try:
                    text = line.strip()
                    if not text:
                        continue
                    msg = json.loads(text)
                except Exception:
                    continue
                # 响应有 id:塞到队列(可能堆积,主线程会取)
                if "id" in msg:
                    try:
                        self._response_queue.put_nowait(msg)
                    except Exception:
                        pass
                # 通知:暂不处理
        except Exception as e:
            _logger.warning("[MCPClient] %s read_loop 退出: %s", self.config.name, e)
        finally:
            self._connected = False


def parse_command_string(cmd_str: str) -> List[str]:
    """
    把 shell-style 字符串解析为参数列表
    "python -m foo --bar baz" → ["python", "-m", "foo", "--bar", "baz"]
    """
    return shlex.split(cmd_str)
