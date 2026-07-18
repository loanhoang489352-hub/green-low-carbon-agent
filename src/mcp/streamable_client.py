"""
MCP Streamable HTTP 客户端 — 通过 HTTP/JSON-RPC 连接 MCP server

P10.B: 遵循 MCP 2025-11-25 规范,使用 Streamable HTTP 传输(替代旧 SSE-only)

协议要点(2025-11-25 规范):
- 单端点(默认 /mcp),支持 POST/GET/DELETE 三种方法
  * POST: 客户端→服务端 JSON-RPC 请求
  * GET:  客户端订阅服务端主动通知(SSE 长连接)
  * DELETE: 终止会话
- POST 响应可为 application/json(单条响应)或 text/event-stream(流式)
- 头:
  * Mcp-Session-Id: 会话 ID(initialize 后由服务端下发)
  * MCP-Protocol-Version: 协议版本(initialize 后必填)
  * Accept: 必须同时含 application/json 和 text/event-stream
  * Origin: 必须(浏览器场景),服务端会校验(GFW 安全)
- OAuth 2.1: 可选,本实现给 stub(实际项目需要时再接完整流程)

向后兼容:
- 与现有 stdio MCPClient 接口对齐:connect / disconnect / list_tools / call_tool
- MCPRegistry 通过 transport 字段分发

P11.C: 支持 YAML 中 ${ENV_VAR} 占位符展开(headers / oauth_* 字段),
用于真实 MCP server(GitHub / Notion 等)的 token 注入。

零新依赖:用现有 httpx(>=0.27)+ threading + queue
"""

from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

_logger = logging.getLogger(__name__)

# MCP 2025-11-25 协议常量
PROTOCOL_VERSION = "2025-11-25"
LEGACY_PROTOCOL_VERSION = "2024-11-05"  # 兼容旧 server
CLIENT_INFO = {"name": "green-low-carbon-agent", "version": "2.0"}
DEFAULT_TIMEOUT_S = 30.0
DEFAULT_CONNECT_TIMEOUT_S = 10.0
DEFAULT_ORIGIN = "https://green-low-carbon-agent.local"


@dataclass
class StreamableHTTPClientConfig:
    """Streamable HTTP MCP 客户端配置"""

    name: str  # 内部唯一名
    url: str  # MCP server 端点(如 https://mcp.notion.com/mcp)
    transport: str = "streamable-http"  # 固定字段
    headers: Dict[str, str] = field(default_factory=dict)  # 自定义请求头(Authorization 等)
    origin: Optional[str] = DEFAULT_ORIGIN  # Origin 头(浏览器场景)
    allowed_origins: List[str] = field(default_factory=list)  # 服务端校验 Origin 白名单(可选)
    protocol_version: str = PROTOCOL_VERSION  # MCP 协议版本
    connect_timeout_s: float = DEFAULT_CONNECT_TIMEOUT_S
    request_timeout_s: float = DEFAULT_TIMEOUT_S
    verify_ssl: bool = True  # 生产应 True;INSECURE_SKIP_VERIFY=true 时降为 False
    description: str = ""
    enabled: bool = True
    # OAuth 2.1(可选)
    oauth_token: Optional[str] = None
    oauth_refresh_token: Optional[str] = None
    oauth_token_url: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None


@dataclass
class MCPTool:
    """远程 MCP 工具描述(与 stdio client 共享结构)"""

    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    server_name: str = ""


@dataclass
class StreamableHTTPServerInfo:
    """Streamable HTTP MCP server 状态"""

    name: str
    status: str  # "connected" | "disconnected" | "error" | "disabled"
    url: str
    session_id: Optional[str] = None
    tools_count: int = 0
    error: Optional[str] = None
    connected_at: Optional[float] = None
    server_info: Optional[Dict[str, Any]] = None


class StreamableHTTPClient:
    """
    MCP Streamable HTTP 客户端(同步接口,内部用 httpx)

    用法:
        cfg = StreamableHTTPClientConfig(
            name="notion",
            url="https://mcp.notion.com/mcp",
            headers={"Authorization": "Bearer ..."},
        )
        client = StreamableHTTPClient(cfg)
        if client.connect():
            tools = client.list_tools()
            result = client.call_tool("search", {"query": "..."})
            client.disconnect()

    设计要点:
    - 公开方法同步,内部 httpx.Client(httpx 默认同步)
    - POST 响应:优先解析 application/json,若返 text/event-stream 则实时解析 SSE
    - Origin 校验:客户端负责发送正确 Origin,服务端校验在 server 侧(本文件给 server 端辅助)
    - OAuth:仅 stub,真实刷新留 TODO
    """

    def __init__(self, config: StreamableHTTPClientConfig):
        self.config = config
        self._session_id: Optional[str] = None
        self._protocol_version: Optional[str] = None
        self._server_info: Optional[Dict[str, Any]] = None
        self._connected = False
        self._connected_at: Optional[float] = None
        self._error: Optional[str] = None
        self._request_id = 0
        self._write_lock = threading.Lock()
        self._client: Optional[httpx.Client] = None
        # 后台 SSE 流(GET 订阅服务端主动通知;本实现读 request/response 优先)
        self._sse_thread: Optional[threading.Thread] = None
        self._stop_sse = threading.Event()
        self._notification_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        # Origin 白名单校验辅助
        self._allowed_origins = set(config.allowed_origins or [])

    # ============ 公共属性 ============

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    # ============ 公开方法(与 stdio client 对齐) ============

    def connect(self) -> bool:
        """
        发起 initialize 握手(P10.B: 同步)
        成功返 True,失败返 False(error 属性可查)
        """
        if not self.config.enabled:
            self._error = "disabled by config"
            return False
        try:
            self._client = httpx.Client(
                timeout=httpx.Timeout(
                    self.config.request_timeout_s,
                    connect=self.config.connect_timeout_s,
                ),
                verify=self.config.verify_ssl,
            )
            # 1. POST initialize
            result = self._post_request(
                "initialize",
                {
                    "protocolVersion": self.config.protocol_version,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
                timeout=self.config.connect_timeout_s,
                skip_session_header=True,
            )
            if "error" in result:
                self._error = f"initialize error: {result['error']}"
                self._cleanup()
                return False
            self._server_info = result.get("result", {})
            # 2. 解析服务端返回的协议版本(如未给,沿用客户端配置的)
            self._protocol_version = (
                self._server_info.get("protocolVersion")
                or self.config.protocol_version
            )
            # 3. 启动后台 GET SSE 线程(订阅服务端主动通知)
            self._stop_sse.clear()
            self._sse_thread = threading.Thread(
                target=self._sse_loop,
                name=f"mcp-http-sse-{self.config.name}",
                daemon=True,
            )
            self._sse_thread.start()
            # 4. 发送 initialized 通知
            self._post_notification("notifications/initialized", {})
            self._connected = True
            self._connected_at = time.time()
            self._error = None
            _logger.info(
                "[StreamableHTTPClient] %s 已连接: server=%s v%s session=%s",
                self.config.name,
                self._server_info.get("serverInfo", {}).get("name", "?"),
                self._server_info.get("serverInfo", {}).get("version", "?"),
                self._session_id,
            )
            return True
        except Exception as e:
            self._error = f"{type(e).__name__}: {str(e)[:200]}"
            self._cleanup()
            _logger.warning(
                "[StreamableHTTPClient] %s 连接失败: %s", self.config.name, self._error
            )
            return False

    def disconnect(self) -> None:
        """关闭连接:发 DELETE 终止会话(若已连接)"""
        if self._connected and self._client and self._session_id:
            try:
                self._client.delete(
                    self._normalize_url(self.config.url),
                    headers=self._build_headers(),
                )
            except Exception:
                pass
        self._cleanup()

    def list_tools(self) -> List[MCPTool]:
        """列出 server 提供的所有 tool"""
        if not self._connected:
            return []
        try:
            result = self._post_request("tools/list", {})
            if "error" in result:
                _logger.warning(
                    "[StreamableHTTPClient] %s list_tools 错误: %s",
                    self.config.name,
                    result["error"],
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
            _logger.warning(
                "[StreamableHTTPClient] %s list_tools 异常: %s", self.config.name, e
            )
            return []

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """调用远程 tool"""
        if not self._connected:
            return {"success": False, "error": "client not connected"}
        try:
            result = self._post_request(
                "tools/call",
                {"name": name, "arguments": arguments or {}},
                timeout=self.config.request_timeout_s,
            )
            if "error" in result:
                return {"success": False, "error": str(result["error"])[:500]}
            return {"success": True, "content": result.get("result", {})}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}

    # ============ OAuth 2.1(stub) ============

    def refresh_oauth_token(self) -> bool:
        """
        OAuth 2.1 token 刷新(stub)
        TODO: 接 RFC 6749 / 8252 完整流程(client_credentials / refresh_token)
        现阶段只刷新内部状态;若 oauth_token_url 未配直接失败
        """
        if not self.config.oauth_token_url:
            self._error = "oauth not configured"
            return False
        # stub: 不实际请求,只记录日志;真实实现应 POST token_url + grant_type=refresh_token
        _logger.warning(
            "[StreamableHTTPClient] %s OAuth refresh 是 stub,需手动注入新 token",
            self.config.name,
        )
        return False

    # ============ 内部:HTTP 通信 ============

    def _build_headers(self, skip_session: bool = False) -> Dict[str, str]:
        """构造请求头"""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.config.origin:
            headers["Origin"] = self.config.origin
        # 自定义头(Authorization 等)
        for k, v in (self.config.headers or {}).items():
            headers[k] = v
        # OAuth bearer
        if self.config.oauth_token and "Authorization" not in headers:
            headers["Authorization"] = f"Bearer {self.config.oauth_token}"
        # 会话头
        if not skip_session and self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        # 协议版本头(initialize 后必填)
        if self._protocol_version:
            headers["MCP-Protocol-Version"] = self._protocol_version
        return headers

    def _post_request(
        self,
        method: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None,
        skip_session_header: bool = False,
    ) -> Dict[str, Any]:
        """POST 单条 JSON-RPC 请求,同步等响应"""
        if not self._client:
            return {"error": "client not initialized"}
        with self._write_lock:
            self._request_id += 1
            request_id = self._request_id
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
            url = self._normalize_url(self.config.url)
            headers = self._build_headers(skip_session=skip_session_header)
            try:
                resp = self._client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout or self.config.request_timeout_s,
                )
            except Exception as e:
                return {"error": f"HTTP error: {type(e).__name__}: {str(e)[:200]}"}

            # 202 Accepted:服务端异步,响应走 SSE 通道(简单场景下不常见)
            if resp.status_code == 202:
                return {"error": "request accepted asynchronously (202), not handled"}

            # 非 2xx:尝试提取错误 JSON
            if resp.status_code < 200 or resp.status_code >= 300:
                try:
                    err_body = resp.json()
                except Exception:
                    err_body = {"message": resp.text[:500]}
                return {"error": f"HTTP {resp.status_code}: {err_body}"}

            # 抓 session id(initialize 响应下发,后续响应也可能刷新)
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid

            # 解析响应(application/json 或 text/event-stream)
            content_type = resp.headers.get("Content-Type", "")
            if "text/event-stream" in content_type:
                return self._parse_sse_response(resp)
            try:
                body = resp.json()
            except Exception as e:
                return {"error": f"invalid JSON response: {e}"}
            return body

    def _post_notification(self, method: str, params: Dict[str, Any]) -> None:
        """POST JSON-RPC 通知(无 id,无响应)"""
        if not self._client:
            return
        with self._write_lock:
            self._request_id += 1
            payload = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
            url = self._normalize_url(self.config.url)
            headers = self._build_headers()
            try:
                self._client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.connect_timeout_s,
                )
            except Exception:
                pass

    def _parse_sse_response(self, resp: httpx.Response) -> Dict[str, Any]:
        """
        解析 text/event-stream 响应
        SSE 格式:
          event: message
          data: {"jsonrpc":"2.0","id":1,"result":...}

        这里取最后一条 data(JSON-RPC 响应)作为返回值
        """
        last_data: Optional[Dict[str, Any]] = None
        try:
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if not chunk:
                        continue
                    try:
                        last_data = json.loads(chunk)
                    except Exception:
                        continue
        except Exception as e:
            return {"error": f"SSE parse error: {e}"}
        if last_data is None:
            return {"error": "empty SSE response"}
        return last_data

    def _sse_loop(self) -> None:
        """
        后台线程:GET 同端点建立 SSE 长连接,接收服务端主动通知
        失败/断开只记日志,不致命
        """
        if not self._client or not self._session_id:
            return
        url = self._normalize_url(self.config.url)
        headers = self._build_headers()
        # 移除 Content-Type(GET 不带 body)
        headers.pop("Content-Type", None)
        try:
            with self._client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    _logger.info(
                        "[StreamableHTTPClient] %s SSE GET 返 %d(可能 server 不支持主动推送)",
                        self.config.name,
                        resp.status_code,
                    )
                    return
                for line in resp.iter_lines():
                    if self._stop_sse.is_set():
                        break
                    if not line:
                        continue
                    if line.startswith("data:"):
                        chunk = line[5:].strip()
                        if not chunk:
                            continue
                        try:
                            msg = json.loads(chunk)
                        except Exception:
                            continue
                        # 通知:无 id,塞到队列(消费者可读)
                        if "id" not in msg:
                            try:
                                self._notification_queue.put_nowait(msg)
                            except Exception:
                                pass
        except Exception as e:
            _logger.info(
                "[StreamableHTTPClient] %s SSE 循环退出: %s", self.config.name, e
            )

    def _normalize_url(self, url: str) -> str:
        """规范化 URL(去尾斜杠,避免双 //)"""
        return url.rstrip("/") if url else url

    def _cleanup(self) -> None:
        self._stop_sse.set()
        if self._sse_thread and self._sse_thread.is_alive():
            try:
                self._sse_thread.join(timeout=1.0)
            except Exception:
                pass
        self._sse_thread = None
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
        self._client = None
        self._connected = False
        self._session_id = None
        self._server_info = None


# ============ Origin 校验辅助(给 server 侧或测试用) ============


def validate_origin(origin: Optional[str], allowed: List[str]) -> bool:
    """
    校验 Origin 头是否在白名单内
    allowed 为空 = 不限制(开发模式)
    生产应配 allowed_origins = ["https://your-domain.com"]
    """
    if not allowed:
        return True
    if not origin:
        return False
    return origin in allowed


def build_streamable_http_config_from_yaml(yaml_dict: Dict[str, Any]) -> StreamableHTTPClientConfig:
    """
    从 yaml dict 构造 StreamableHTTPClientConfig(供 MCPRegistry.load_config 用)

    P11.C: 对 headers / oauth_* 等字符串字段做 ${ENV_VAR} 占位符展开。
    未找到的环境变量保留原样(避免 silent loss,用户能看到未展开的占位符)。

    期望字段:
      name, url, transport: streamable-http, headers: {}, origin: ..., ...
    """
    return StreamableHTTPClientConfig(
        name=yaml_dict.get("name", "mcp_http"),
        url=yaml_dict.get("url", ""),
        transport="streamable-http",
        headers=_expand_env_in_mapping(yaml_dict.get("headers", {}) or {}),
        origin=yaml_dict.get("origin", DEFAULT_ORIGIN),
        allowed_origins=yaml_dict.get("allowed_origins", []) or [],
        protocol_version=yaml_dict.get("protocol_version", PROTOCOL_VERSION),
        connect_timeout_s=float(yaml_dict.get("connect_timeout_s", DEFAULT_CONNECT_TIMEOUT_S)),
        request_timeout_s=float(yaml_dict.get("request_timeout_s", DEFAULT_TIMEOUT_S)),
        verify_ssl=bool(yaml_dict.get("verify_ssl", True)),
        description=yaml_dict.get("description", ""),
        enabled=bool(yaml_dict.get("enabled", True)),
        oauth_token=_expand_env_in_string(yaml_dict.get("oauth_token")),
        oauth_refresh_token=_expand_env_in_string(yaml_dict.get("oauth_refresh_token")),
        oauth_token_url=_expand_env_in_string(yaml_dict.get("oauth_token_url")),
        oauth_client_id=_expand_env_in_string(yaml_dict.get("oauth_client_id")),
        oauth_client_secret=_expand_env_in_string(yaml_dict.get("oauth_client_secret")),
    )


# ============ P11.C: ${ENV_VAR} 占位符展开 ============

_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


def _expand_env_in_string(value: Any) -> Any:
    """
    展开字符串中的 ${ENV_VAR} 占位符。
    - 若 value 不是字符串,直接返回
    - 未找到的 env 保留原样(以 `${VAR_NAME}` 形式),便于 debug
    """
    if not isinstance(value, str):
        return value

    def _repl(m: "re.Match[str]") -> str:
        var_name = m.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            return m.group(0)  # 保留原占位符
        return env_val

    return _ENV_PATTERN.sub(_repl, value)


def _expand_env_in_mapping(d: Dict[str, Any]) -> Dict[str, Any]:
    """对 dict 的 value 做 ${ENV_VAR} 展开"""
    return {k: _expand_env_in_string(v) for k, v in d.items()}


def expand_mcp_yaml_placeholders(yaml_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    对整个 MCP yaml dict 做 env 占位符展开(递归 dict / list / string)。
    供 stdio 与 streamable-http 配置统一入口使用。
    """
    return _recursive_expand(yaml_dict)


def _recursive_expand(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _recursive_expand(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_recursive_expand(v) for v in obj]
    if isinstance(obj, str):
        return _expand_env_in_string(obj)
    return obj