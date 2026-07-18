# P11.真实 MCP 接入 学习手册 — 给用户的 15 分钟上手

> 适用对象:想用 GitHub / Notion 等真实工具增强智能体的开发者 / 用户。
> 阅读时间:约 15 分钟。
> 读完之后能回答:**怎么开 GitHub MCP / token 怎么填 / Notion 怎么授权 / 怎么验证生效 / 排错**。

---

## 1. P11.C 是什么

P10.B 已经在 `config/mcp_servers.yaml` 里加了 **mock HTTP server**,可以本地跑通端到端流程。但要做真实场景(查 GitHub 仓库、读 Notion 页面)就得接 **真实 MCP server**。

P11.C 做两件事:

1. **GitHub MCP server 接入** — 用户填 1 个 GitHub PAT(`GITHUB_TOKEN`),agent 就能调 GitHub 官方 MCP 暴露的工具(`create_issue` / `list_repos` / `get_file_contents` 等 30+ 个)
2. **Notion MCP 模板** — Notion 官方 MCP 走 OAuth,模板已配好,填 `NOTION_CLIENT_ID` / `NOTION_CLIENT_SECRET` 即可用

所有 token 走 **环境变量**(`${GITHUB_TOKEN}`),**不写进 yaml**,这样 git diff 不会泄密。环境变量由 YAML loader 自动展开。

---

## 2. 怎么开 GitHub MCP

### 2.1 创建 fine-grained PAT

GitHub MCP server 需要一个 **personal access token (PAT)**。推荐用 fine-grained PAT(权限最小化):

1. 打开 https://github.com/settings/tokens?type=beta
2. **Generate new token** → 选 fine-grained
3. **Resource owner**: 选你想要的 organization 或自己的账号
4. **Repository access**: 至少勾 **Public Repositories (read-only)**,如果要写 issue 则勾对应的 private repo
5. **Permissions**:
   - Repository → **Contents**: Read
   - Repository → **Issues**: Read and write(若要创建 issue)
   - Repository → **Pull requests**: Read
   - Account → **Profile**: Read(读 user profile)
6. 生成 token,复制(`ghp_xxx...`)

### 2.2 设置环境变量

把 token 填进 `.env`:

```bash
# .env (git 已 ignore)
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 2.3 启用 yaml 配置

打开 `config/mcp_servers.yaml`,把 `github` 那条的 `enabled` 改成 `true`:

```yaml
- name: github
  description: GitHub 官方 MCP(Streamable HTTP)
  enabled: true          # ← 改这里
  transport: streamable-http
  url: https://api.githubcopilot.com/mcp/
  headers:
    Authorization: Bearer ${GITHUB_TOKEN}
  origin: https://green-low-carbon-agent.local
  connect_timeout_s: 10.0
  request_timeout_s: 30.0
  verify_ssl: true
```

### 2.4 重启服务

```bash
# 重启后,server 会自动:
# 1. 读取 GITHUB_TOKEN
# 2. POST initialize 到 https://api.githubcopilot.com/mcp/
# 3. 调 tools/list,拿到 30+ 个 GitHub 工具
# 4. 注册到本地 ToolRegistry(前缀 mcp_github_)
cd src && python main.py
```

### 2.5 验证生效

启动后查 `/api/mcp/status`:

```bash
curl http://localhost:8000/api/mcp/status | python -m json.tool
```

期望看到:

```json
{
  "servers_count": 3,
  "tools_count": 33,
  "servers": [
    {
      "name": "github",
      "status": "connected",
      "tools_count": 30,
      "url": "https://api.githubcopilot.com/mcp/"
    },
    ...
  ]
}
```

也可以查 `/api/tools-skills`,在 tools 列表里找 `mcp_github_*` 前缀的工具:

```bash
curl http://localhost:8000/api/tools-skills | python -m json.tool | grep -i github
```

---

## 3. 怎么用 Notion MCP

### 3.1 创建 Notion integration

1. 打开 https://www.notion.so/profile/integrations
2. **Create new integration** → 选 workspace
3. **Type**: Internal
4. **Capabilities**: 至少勾 Read content / Update content / Insert content
5. 创建后会拿到 **Internal Integration Token**(`secret_xxx...`),先复制保存
6. 在 Notion 里把要操作的 page / database **share 给这个 integration**(右上角 Share → Invite)

### 3.2 设置环境变量

```bash
# .env
NOTION_TOKEN=secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
NOTION_CLIENT_ID=             # 可选:OAuth 用
NOTION_CLIENT_SECRET=         # 可选:OAuth 用
```

### 3.3 启用 yaml 配置

`config/mcp_servers.yaml` 把 `notion` 的 `enabled: true`,并补全 `oauth_token`:

```yaml
- name: notion
  description: Notion 官方 MCP
  enabled: true          # ← 改这里
  transport: streamable-http
  url: https://mcp.notion.com/mcp
  oauth_token: ${NOTION_TOKEN}    # ← 取消注释
  origin: https://green-low-carbon-agent.local
  ...
```

> **注**:Notion 官方 MCP 当前用 OAuth 2.1,我们的客户端实现了 stub(自动 bearer 注入 + OAuth token 字段)。真实 OAuth 流程(authorization_code → token exchange)需要走完整 RFC 6749 实现,目前建议先用 `oauth_token` 直接填 integration token。

### 3.4 验证

同 §2.5,期望看到 `notion` server `status: connected` + 工具前缀 `mcp_notion_*`。

---

## 4. 排错指南

### 4.1 `status: "error"` + `error: "HTTP 401"`

**症状**:`/api/mcp/status` 显示 GitHub server 401。

**原因**:token 无效 / 过期 / 权限不够。

**修复**:
- 重新生成 PAT(§2.1)
- 确认 `.env` 里 `GITHUB_TOKEN=` 后面没空格
- 确认 fine-grained PAT 给到了对应仓库的读权限

### 4.2 `status: "error"` + `error: "ConnectError"`

**症状**:连不上 GitHub server。

**原因**:网络问题(国内到 `api.githubcopilot.com` 可能不稳)。

**修复**:
- 检查能否 `curl -I https://api.githubcopilot.com/mcp/`(应返 405 / 400,而不是 timeout)
- 如走代理,设 `HTTPS_PROXY=http://127.0.0.1:7890`
- 临时把 `connect_timeout_s` 调到 30.0

### 4.3 `${GITHUB_TOKEN}` 没展开

**症状**:server log 显示 `Authorization: Bearer ${GITHUB_TOKEN}`(没被替换)。

**原因**:环境变量没设,或 `MCPRegistry.load_config` 早于 `os.environ.get` 读取。

**修复**:
- 确认 `.env` 加载:本项目用 `python-dotenv` 或启动脚本 `set -a; source .env; set +a`
- 重启服务(env 在子进程 fork 时才继承)

### 4.4 tools 列表为空

**症状**:server `connected` 但 `tools_count: 0`。

**原因**:MCP server initialize 成功,但 `tools/list` 返回空(权限不够,或 server 端 bug)。

**修复**:查 `data/logs/app.log` 看 `[MCPRegistry] %s list_tools 失败: %s`

### 4.5 Notion 401

**症状**:Notion server 返 401。

**原因**:integration 没被 share 到对应 page。

**修复**:在 Notion 里打开目标 page → 右上角 Share → 邀请刚才创建的 integration。

---

## 5. 安全注意事项

1. **Token 不要 commit 到 git** — `.env` 已在 `.gitignore`,但 yaml 里若误把 token 直接写进去(不带 `${...}`)会泄密。可用 `git log -p config/mcp_servers.yaml | grep -i "ghp_"` 扫历史。
2. **最小权限** — fine-grained PAT 只勾必要的仓库和权限
3. **定期轮换** — PAT 90 天 / 180 天换一次,避免泄露后长期有效
4. **生产用 Vault** — K8s 环境把 `GITHUB_TOKEN` 注入到 Secret,不进 yaml

---

## 6. 进阶:接其他 MCP server

任何支持 Streamable HTTP transport 的 MCP server 都能接。模板见 `config/mcp_servers.yaml` 注释或 `docs/operations/p11-real-mcp.md`。

关键 3 步:

1. 写 `name + url + transport: streamable-http`
2. `headers: { Authorization: Bearer ${TOKEN} }`(如有 token)
3. `enabled: true`

详细的 YAML schema 见 `docs/operations/p11-real-mcp.md`。