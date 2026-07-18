# P11.真实 MCP server 接入 操作手册 — 给运维 / 二次开发者

> 适用对象:想给智能体接新 MCP server 的开发者、运维。
> 阅读时间:约 20 分钟。
> 读完之后能回答:**YAML schema 是什么 / 怎么填 token / 怎么测 / 怎么排错 / 怎么贡献新 server 模板**。

---

## 1. 概述

P11.C 在 `config/mcp_servers.yaml` 加了 2 个真实 MCP server 模板(**GitHub** + **Notion**)和 1 个 `${ENV_VAR}` 占位符展开机制。

任何支持 **MCP Streamable HTTP transport**(2025-11-25 规范)的 server 都能接。本文档给出:

1. 完整 YAML schema 字段表
2. 占位符展开规则
3. 添加新 server 的步骤(含审批要点)
4. 排错清单

---

## 2. 完整 YAML schema

### 2.1 顶层结构

```yaml
mcp_servers:                  # 顶层 list,也可写 servers: (兼容)
  - name: <string, 必填>       # 内部唯一标识
    description: <string>      # 显示在 /api/mcp/status / /api/tools-skills
    enabled: <bool>            # 默认 true;真实 server 推荐 false(用户主动开)
    transport: <string>        # "stdio" | "streamable-http"
    # ---- transport 字段 ----
    command: <string>          # [stdio] 可执行命令(python / node / ...)
    args: [<string>, ...]      # [stdio] 命令参数
    env:                       # [stdio] 额外环境变量(key-value, value 支持 ${ENV})
      KEY: value
    cwd: <string>              # [stdio] 工作目录(默认 project_root)

    url: <string>              # [streamable-http] MCP server 端点
    headers:                   # [streamable-http] 自定义请求头(支持 ${ENV} 展开)
      Authorization: Bearer ${TOKEN}
      X-Custom: literal
    origin: <string>           # [streamable-http] Origin 头(浏览器场景必填)
    allowed_origins: [<string>] # [server 侧] 客户端 Origin 白名单

    oauth_token: <string>      # [streamable-http] OAuth bearer(token 字段支持 ${ENV})
    oauth_refresh_token: <string>
    oauth_token_url: <string>  # refresh 端点(stub 阶段,真实流程留 TODO)
    oauth_client_id: <string>
    oauth_client_secret: <string>

    connect_timeout_s: <float> # 默认 10.0
    request_timeout_s: <float> # 默认 30.0
    verify_ssl: <bool>         # 默认 true;INSECURE_SKIP_VERIFY=true 全局豁免
```

### 2.2 必填字段

| transport | 必填 | 可选 |
|-----------|------|------|
| `stdio`   | `name`, `transport`, `command`, `args` | `env`, `cwd`, `description`, `enabled`, timeouts |
| `streamable-http` | `name`, `transport`, `url` | `headers`, `origin`, OAuth 字段, timeouts, `verify_ssl` |

---

## 3. 占位符展开规则

P11.C 加了 `${ENV_VAR}` 占位符展开机制,适用于**所有字符串字段**(headers / oauth_* / url / env.value)。

### 3.1 语法

```yaml
headers:
  Authorization: Bearer ${GITHUB_TOKEN}
oauth_token: ${NOTION_TOKEN}
```

### 3.2 规则

- 命中: `${VAR}` 替换为 `os.environ['VAR']` 的值
- 未命中: **保留原样**(`${VAR}` 不变),便于 debug(用户能看到漏配的变量)
- 大小写:变量名只匹配 `[A-Z_][A-Z0-9_]*`(全大写 + 下划线)
- 递归:对 dict / list / string 都生效

### 3.3 验证

```python
from mcp.streamable_client import _expand_env_in_string
import os
os.environ["FOO"] = "bar"
assert _expand_env_in_string("hello ${FOO}") == "hello bar"
```

### 3.4 安全注意

- `.env` 文件必须在 `.gitignore`(本项目已配)
- yaml 里写 `${TOKEN}` 是**安全的**(git diff 只看到占位符),但写成 `Bearer ghp_xxx` 直接 commit 会泄密
- 生产建议用 **Vault / K8s Secret** 注入 env,而不是 `.env`

---

## 4. 添加新 MCP server 的步骤

### 4.1 选择 server

先确认 server 支持的 transport:

- **stdio** — server 是个可执行命令(python / node / binary)
- **streamable-http** — server 暴露 HTTP 端点,响应 JSON-RPC

主流 MCP server 列表(2026-07):
- GitHub(github/github-mcp-server)— 已支持
- Notion — 已支持(模板)
- Filesystem(@modelcontextprotocol/server-filesystem)— stdio
- Postgres — stdio
- Brave Search — stdio
- Google Drive — streamable-http(官方)
- Slack — streamable-http(官方)

### 4.2 写 yaml 条目

假设要接 **Brave Search MCP**:

```yaml
- name: brave_search
  description: Brave Search 官方 MCP — 实时联网搜索
  enabled: false
  transport: stdio
  command: npx
  args:
    - -y
    - "@modelcontextprotocol/server-brave-search"
  env:
    BRAVE_API_KEY: ${BRAVE_API_KEY}
  connect_timeout_s: 10.0
  request_timeout_s: 30.0
```

streamable-http 例(假设 URL 端点):

```yaml
- name: custom
  transport: streamable-http
  url: https://my-mcp.example.com/mcp
  headers:
    Authorization: Bearer ${CUSTOM_TOKEN}
  origin: https://green-low-carbon-agent.local
```

### 4.3 本地测试

#### 4.3.1 配置解析测试

```python
# 验证 yaml 能解析,且占位符展开正确
import os
os.environ["BRAVE_API_KEY"] = "BSA-test-key"

from mcp import MCPRegistry
reg = MCPRegistry()
configs = reg.load_config("config/mcp_servers.yaml")
brave = next(c for c in configs if c.name == "brave_search")
assert brave.env["BRAVE_API_KEY"] == "BSA-test-key"
```

#### 4.3.2 真实连接测试

把 `enabled: true`,启动服务,查 `/api/mcp/status`:

```bash
curl -s http://localhost:8000/api/mcp/status | python -m json.tool
```

期望看到 `brave_search` server `status: connected` + `tools_count >= 1`。

#### 4.3.3 通过本地 ToolRegistry 调用

```python
from agent.tools import get_registry as get_tool_registry

reg = get_tool_registry()
tool = reg.get("mcp_brave_search_search")
result = tool.execute(query="latest carbon market news", count=5)
assert result.success
print(result.data["text"])
```

### 4.4 跑测试套件

P11.C 加了 2 个测试文件覆盖:

- `tests/test_real_mcp_config.py` — 配置解析 + 占位符展开(13 个 case)
- `tests/test_real_mcp_github.py` — 端到端 mock GitHub MCP(8 个 case)

新 server 应至少覆盖:

```python
def test_your_server_<feature>():
    """<server> MCP <feature> 测试"""
    # 1. mock server 起来
    # 2. StreamableHTTPClient.connect() 成功
    # 3. list_tools() 拿到预期 tool 列表
    # 4. call_tool(name, args) 返回预期结果
    # 5. token 错误 → 401
```

参考 `tests/test_real_mcp_github.py` 的 `_GitHubMockServer` 实现,基于 `http.server` stdlib。

---

## 5. 排错清单

| 症状 | 根因 | 排查步骤 |
|------|------|---------|
| `${VAR}` 没展开 | env 没设 | `echo $VAR` / `.env` 是否加载 |
| 401 Unauthorized | token 无效 | 重生成;检查格式(ghp_/secret_ 前缀) |
| ConnectError | 网络 | `curl -I <url>`;HTTPS_PROXY |
| tools_count: 0 | permission 不足 | log: `[MCPRegistry] X list_tools 失败` |
| 进程启动 hang | stdio server 卡 initialize | 加 `connect_timeout_s: 5.0` |
| Origin 403 | server 端 Origin 校验失败 | `allowed_origins` 配 server URL |

更细的 debug:

- `data/logs/app.log` — JSON 格式,带 trace_id,grep `mcp` 关键字
- `data/logs/error.log` — 堆栈
- `GET /api/mcp/status` — 实时状态

---

## 6. 贡献新 server 模板到仓库

提交 PR 时请附:

1. yaml 条目(注释用 `# P11.C: <server name>` 标记)
2. 测试文件(参考 `tests/test_real_mcp_github.py` 的 mock server 模板)
3. `docs/learning/p11-real-mcp.md` 加一节(怎么用 + token 怎么拿)

CI 检查项(2026-07 起):

- `pytest tests/test_real_mcp_*.py -v` 全过
- 新 server 默认 `enabled: false`
- 占位符用 `${ENV_VAR}` 格式,不直接写 token
- 不引入新依赖(用现有 httpx + threading)

---

## 7. 已知限制

1. **OAuth 2.1 完整流程** — 当前 `oauth_token` 是直接注入 bearer,`refresh_oauth_token()` 是 stub(返 False,需手动更新)。完整 OAuth(authorization_code + PKCE)需要 RFC 6749 + 8252 实现,留 P11.D。
2. **stdio server 输出缓冲** — Windows 上 Popen + text mode 可能 buffer 不刷新;若 server 卡住,加 `PYTHONUNBUFFERED=1` env。
3. **GitHub Copilot MCP 限流** — 免费 PAT 60 req/h;高频调用需升级 GH Pro / Enterprise。
4. **Notion OAuth 完整流程** — 当前用 integration token 直连,未走授权码;P11.D 实现完整 OAuth 浏览器跳转。

---

## 8. 附录:常见 MCP server 配置示例

### 8.1 GitHub

```yaml
- name: github
  enabled: false
  transport: streamable-http
  url: https://api.githubcopilot.com/mcp/
  headers:
    Authorization: Bearer ${GITHUB_TOKEN}
  origin: https://green-low-carbon-agent.local
```

### 8.2 Notion

```yaml
- name: notion
  enabled: false
  transport: streamable-http
  url: https://mcp.notion.com/mcp
  oauth_token: ${NOTION_TOKEN}
```

### 8.3 Filesystem(stdio)

```yaml
- name: filesystem
  enabled: false
  transport: stdio
  command: npx
  args:
    - -y
    - "@modelcontextprotocol/server-filesystem"
    - "/path/to/allowed/dir"
```

### 8.4 Postgres(stdio)

```yaml
- name: postgres
  enabled: false
  transport: stdio
  command: npx
  args:
    - -y
    - "@modelcontextprotocol/server-postgres"
    - "postgresql://user:pass@localhost:5432/db"
```

### 8.5 高德地图(若已有 stdio server)

```yaml
- name: amap
  enabled: false
  transport: stdio
  command: python
  args:
    - /path/to/amap_mcp_server.py
  env:
    GAODE_API_KEY: ${GAODE_API_KEY}
```