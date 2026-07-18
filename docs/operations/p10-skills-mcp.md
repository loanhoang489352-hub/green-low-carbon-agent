# P10 Skills + P11 MCP — SRE / 运维手册

> **受众**:运维工程师 / 值班 SRE。熟 Linux + Docker + MCP 基本概念,刚接触本项目也能照着命令排障。
> **目标**:出问题时 **5 分钟内** 定位根因 + 应急。
> **适用版本**:v2.2+ / P10.A + P11.B(2026-07-18)。
> **最后更新**:2026-07-18。

---

## 目录

1. [P10 + P11 在生产环境的形态](#1-p10--p11-在生产环境的形态)
2. [关键指标(KPI)](#2-关键指标kpi)
3. [告警规则](#3-告警规则)
4. [常见故障 + 排查](#4-常见故障--排查)
5. [应急操作(无需重启)](#5-应急操作无需重启)
6. [维护任务](#6-维护任务)
7. [升级 / 回滚](#7-升级--回滚)
8. [联系 / 升级流程](#8-联系--升级流程)

---

## 1. P10 + P11 在生产环境的形态

P10 标准化 Skills(Anthropic Skills 规范 2026-01 GA),P11 给 MCP 加 Streamable HTTP 传输(2025-11-25 规范,替代旧 SSE-only)。两者一起构成**本地工具的可组合 + 远端工具的可插拔**双层抽象。

```
/api/chat/enhanced
   │
   ▼
[LangGraph ReAct 节点]
   │
   ├─→ 本地 SkillExecutor(singleton)
   │      ├─ low_carbon_travel   (Skill 1,组合 weather + carbon_calc + public_transit)
   │      ├─ policy_query        (Skill 2,组合 policy_query)
   │      └─ profile_update      (Skill 3,组合 profile_update)
   │           │
   │           ▼  触发后调 BaseTool
   │      [本地 ToolRegistry]
   │           ├─ 内置 tools
   │           └─ MCP 注入的 remote tools(mcp_<server>::<tool>)
   │
   └─→ MCPRegistry(singleton)
          ├─ stdio           → MCPClient → 子进程(JSON-RPC 2.0 over stdin/stdout)
          └─ streamable-http → StreamableHTTPClient → HTTP POST + SSE 长连接
                                 (Origin / session / OAuth stub)
                                          │
                                          ▼
                              把 remote tool 包成 MCPToolAdapter
                              注册到本地 ToolRegistry
```

### 1.1 关键路径与文件位置

| 资源 | 路径 / 来源 |
|---|---|
| Skill 代码 | `src/agent/skills/{skill.py, builtin.py, __init__.py}` |
| 内置 Skill 列表 | `LowCarbonTravelSkill / PolicyQuerySkill / ProfileUpdateSkill`(`builtin.py`) |
| SKILL.md 输出目录 | `<PROJECT_ROOT>/.claude/skills/<skill_name>/SKILL.md`(Anthropic 规范) |
| Skill 全局执行器 | `get_skill_executor()` 单例,懒加载,首次调用时 init |
| MCP 代码 | `src/mcp/{client.py, streamable_client.py, registry.py, adapter.py, server.py}` |
| MCP 配置 | `config/mcp_servers.yaml`(YAML,transport 字段分发 stdio / streamable-http) |
| Mock stdio server | `scripts/mcp_mock_server.py`(默认 enabled=true,3 个测试 tool) |
| Mock HTTP server | `scripts/mock_http_mcp_server.py`(默认 enabled=false,本机 8765 端口) |
| Skill 状态端点 | `GET /api/tools-skills` |
| MCP 状态端点 | `GET /api/mcp/status` |
| 主入口 | `src/server/app.py:: _register_all_tools_and_skills()` + `_start_mcp_registry()` |
| 生命周期 | `src/server/lifecycle.py::init_app()` 第 3、4 步 |
| 日志 | `data/logs/app.log`(JSON 行,grep `[MCPRegistry]` / `[MCPClient]` / `[Skill]`) |

### 1.2 容器化注意

容器启动顺序:`tini` → `python src/main.py` → `init_app()` → `register_all_routes` → `_register_all_tools_and_skills()` → `_start_mcp_registry()`(后台线程,mcp-registry) → `_register_event_subscribers` → `_start_scheduler_safe()`。

MCP stdio 是**子进程**模型,容器内必须保证 `subprocess.Popen(stdin=PIPE, stdout=PIPE)` 拿到的不是 PID 1 的管道(PID 1 用 tini 接管 → 子进程的 stdin/stdout 正常指向自己的管道)。MCP HTTP 是 HTTP POST + SSE,容器需开 `8765`(本地 mock)/ 远端 URL。

---

## 2. 关键指标(KPI)

| 指标 | 阈值 / 健康值 | 数据来源 | 端点 |
|---|---|---|---|
| **Skill 触发准确率**(意图→Skill) | ≥ 90% | `data/logs/app.log` 的 `skill_triggered` 字段聚合 | `scripts/eval_skills.py`(离线) |
| **Skill 平均执行时长** P50 | ≤ 2s / 单次 | `data/logs/app.log` 解析 `skill_latency_ms` | `/api/metrics` |
| **Skill 平均执行时长** P95 | ≤ 10s / 单次(含远端 API) | 同上 | `/api/metrics` |
| **Skill 执行成功率** | ≥ 95%(`success=true` / 总调用) | 日志聚合 | 自定义 Prometheus |
| **内置 Skill 注册数** | = 3(low_carbon_travel / policy_query / profile_update) | `get_skill_executor().list_all()` | `/api/tools-skills` |
| **SKILL.md 文件数** | = Skill 注册数 | `ls .claude/skills/*/SKILL.md \| wc -l` | 手动 |
| **MCP 连接成功率** | 100%(所有 enabled server 应 connected) | `/api/mcp/status` JSON | `/api/mcp/status` |
| **MCP tool 调用成功率** | ≥ 98% | 日志 `[MCPClient] call_tool` success/fail | `/api/metrics` 聚合 |
| **MCP tool 调用 P95 延迟** | ≤ 5s | 日志 `mcp_latency_ms` | `/api/metrics` |
| **stdio 子进程存活数** | = enabled stdio server 数 | `pgrep -fa "python.*mcp_mock_server"` | 手动 |
| **HTTP session 复用率** | ≥ 70%(`session_id` 复用的请求 / 总请求) | 日志 `[StreamableHTTPClient] reused session` | 手动 |
| **后台线程存活** | mcp-registry 线程名存在 | `ps -ef \| grep mcp-registry` | 手动 |
| **Skill 启动时间** | ≤ 1s(`_register_all_tools_and_skills`) | `data/logs/app.log` `[Skill] 注册耗时` | 日志 |

```bash
# 实时拿 Skill / MCP 状态
curl -s http://localhost:8000/api/tools-skills | jq '.skills_count, .skills[].name'
curl -s http://localhost:8000/api/mcp/status | jq '.servers_count, .servers[] | {name, status, tools_count}'

# 计算 Skill 触发准确率(过去 24h)
jq -r 'select(.msg | test("skill_triggered")) |
       "\(.trigger_correct // .correct // "0") \(.skill)"' data/logs/app.log | \
  awk '{ if ($1 == "true" || $1 == "1") hit++; total++ }
       END { print "accuracy=", hit/total, "samples=", total }'

# 数 SKILL.md 文件
ls /opt/green-agent/.claude/skills/*/SKILL.md 2>/dev/null | wc -l
```

### 2.1 离线指标计算脚本

```bash
# 1) Skill 触发准确率(从 JSON 日志聚合,最近 5000 行)
jq -r 'select(.logger | test("skill|executor")) |
       select(.msg | test("trigger")) |
       "\(.ts) \(.skill) \(.expected // "?") \(.actual // "?")"' data/logs/app.log | \
  tail -5000 | awk '{ if ($3 == $4) hit++; total++ }
                     END { print "hit=", hit, "total=", total, "rate=", hit/total }'

# 2) MCP tool 调用错误率(过去 1h)
jq -r 'select(.logger | test("MCPClient|StreamableHTTP")) |
       select(.msg | test("call_tool")) |
       "\(.ts) \(.success // "false")"' data/logs/app.log | \
  awk '{ if ($0 ~ /true/) ok++; else err++ }
       END { print "ok=", ok, "err=", err, "rate=", err/(ok+err) }'

# 3) stdio 子进程存活
pgrep -fa "python.*mcp_mock_server" | wc -l    # 期望 = enabled stdio server 数

# 4) HTTP session 复用率
grep -c "reused session" data/logs/app.log
grep -c "session_id=" data/logs/app.log
```

---

## 3. 告警规则

> 推荐接 Prometheus Alertmanager / 内部 on-call。所有规则都要对单点抖动做去抖(`for: 5m`),避免 MCP 首次冷启动触发误报。

| 严重度 | 规则 | 阈值 | 持续 | 自动动作 |
|---|---|---|---|---|
| **P1** | 全部 MCP server disconnected | `/api/mcp/status` 中 `connected == 0` 且 `enabled > 0` | 1m | 检查 mcp_servers.yaml + 子进程 / HTTP |
| **P2** | MCP 连接成功率 | < 100%(任何 enabled server 状态 ≠ connected) | 5m | `echo MCP_DOWN \| notify` + 查子进程 |
| **P2** | Skill 触发准确率 | < 80% 持续 30min | 30m | 跑 `scripts/eval_skills.py` 找回归 |
| **P2** | Skill 执行成功率 | < 95% 持续 10min | 10m | 查 `data/logs/app.log` `SkillExecutionError` |
| **P2** | Skill P95 延迟 | > 10s | 10m | 检查远端 API(高德 / 天气);CPU |
| **P2** | stdio 子进程频繁重启 | `[MCPClient] 已连接` 后 30s 内再次 `[MCPClient] read_loop 退出` | 5m | 子进程崩了;查 `data/logs/app.log` stderr |
| **P2** | MCP HTTP 401/403 | 日志 `HTTP 401\|403` ≥ 5 / h | 5m | 检查 OAuth / Bearer token 过期 |
| **P2** | MCP HTTP 5xx | 日志 `HTTP 5xx` ≥ 10 / h | 5m | 检查远端 server 健康 |
| **P3** | SKILL.md 缺失 | 注册 3 个 Skill 但 `.claude/skills/` 少于 3 个 SKILL.md | 1h | 跑 `Skill.write_skill_md()` 重生 |
| **P3** | 后台 mcp-registry 线程死 | `ps -ef \| grep mcp-registry` 无输出 | 1m | 重启服务(P5-J 监控未涵盖) |
| **P3** | 内置 Skill 数量异常 | `len(skill_exec.list_all()) != 3` | 5m | 检查 `builtin.py` import 是否被改 |
| **P3** | MCP tool 调用 P95 | > 5s | 10m | 查远端 API 慢;考虑加 timeout |
| **P4** | `.claude/skills/` 写入失败 | 日志 `[Skill] SKILL.md 写入失败` ≥ 1 次 | 1h | 检查 `.claude/` 目录权限 |

### 3.1 告警对应 Prometheus 样例

```yaml
# /etc/prometheus/rules/skills_mcp.yml
groups:
  - name: skills_mcp_alerts
    rules:
      - alert: MCPAllDisconnected
        expr: mcp_connected_servers == 0 and mcp_enabled_servers > 0
        for: 1m
        labels: { severity: page }
        annotations:
          summary: "所有 MCP server 都断连了"
          runbook: docs/operations/p10-skills-mcp.md#4-常见故障

      - alert: MCPServerDown
        expr: mcp_server_status{status="connected"} == 0
        for: 5m
        labels: { severity: page }
        annotations:
          summary: "MCP server {{ $labels.name }} 已断连"

      - alert: SkillAccuracyLow
        expr: skill_trigger_accuracy_24h < 0.80
        for: 30m
        labels: { severity: warn }

      - alert: SkillLatencyHigh
        expr: histogram_quantile(0.95, skill_latency_seconds_bucket) > 10
        for: 10m
        labels: { severity: warn }

      - alert: MCPToolErrorRate
        expr: rate(mcp_tool_errors_total[10m]) / rate(mcp_tool_calls_total[10m]) > 0.02
        for: 5m
        labels: { severity: page }
```

---

## 4. 常见故障 + 排查

> 形式:**症状 → 排查命令 → 修复动作**。

### 4.1 症状:`/api/mcp/status` 返所有 server `status=error`

```bash
# 1) 看具体错误
curl -s http://localhost:8000/api/mcp/status | jq '.servers[] | {name, status, error}'
grep -E "MCPRegistry|MCPClient" data/logs/app.log | tail -20

# 2) 配置是否正确读取
docker exec green-agent cat /app/config/mcp_servers.yaml | head -30
# 期望:mock_server.enabled=true, transport=stdio, command=python, args=[scripts/mcp_mock_server.py]

# 3) stdio 子进程是否能起
docker exec green-agent python scripts/mcp_mock_server.py < /dev/null &
sleep 2
# 期望:进程没立即退出;echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | python ... → 返 pong

# 4) 远端 HTTP server(若启用 streamable-http)是否通
docker exec green-agent curl -I https://mcp.notion.com/mcp 2>&1 | head -5
```

**修复**:
```bash
# a) 配置缺失 / 改坏
vim config/mcp_servers.yaml          # 改后需 docker restart(配置启动时读,不支持热加载)
docker restart green-agent

# b) stdio 子进程崩了(Python 异常)
docker exec green-agent python scripts/mcp_mock_server.py
# 直接跑看 traceback → 修代码或依赖

# c) 远端 server URL 不通
docker exec green-agent curl -v https://<server>/mcp
# 改 url 或 disabled: true

# d) 环境变量缺失(stdio server 启动需要某些 env)
docker exec green-agent env | grep -i GAODE
# 期望有 GAODE_API_KEY(非占位符)
# 缺则写到 .env 或 systemd EnvironmentFile
```

### 4.2 症状:Skill 触发不准(LLM 没选对 Skill)

```bash
# 1) 跑评估脚本
pytest tests/test_skills_compliance.py -v
USE_REAL_LLM=1 python scripts/eval_skills.py
# 期望:trigger_accuracy ≥ 0.90

# 2) 看内置 Skill 的 when_to_use(LLM 据此触发)
docker exec green-agent python -c "
from agent.skills.builtin import LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill
for s in [LowCarbonTravelSkill(), PolicyQuerySkill(), ProfileUpdateSkill()]:
    print(s.name, '|', s.when_to_use)
"
# 期望每条 ≥ 1 个触发关键词

# 3) 校验 SKILL.md 是否生成
ls .claude/skills/*/SKILL.md
docker exec green-agent find /app/.claude/skills -name SKILL.md

# 4) 看真实触发日志
grep "skill_triggered\|SkillExecutor" data/logs/app.log | tail -30
```

**修复**:
```bash
# a) 触发关键词不够(LLM 不确定选哪个)
# 改 builtin.py 里 when_to_use,加 / 或 | 分隔的同义词
vim src/agent/skills/builtin.py    # 改后重启

# b) SKILL.md 没生成(LLM 看不到 metadata)
ls .claude/skills/   # 目录存在?
mkdir -p /opt/green-agent/.claude/skills
chown -R greenagent:greenagent /opt/green-agent/.claude
# 重启服务,会自动重写

# c) Skill 注册数 ≠ 3(代码 import 被改)
docker exec green-agent python -c "
from agent.skills import get_skill_executor
ex = get_skill_executor()
# 触发 import builtin 才能 register
import agent.skills.builtin
print('registered:', ex.list_all())
"
# 期望:['low_carbon_travel', 'policy_query', 'profile_update']
```

### 4.3 症状:Skill execute 报 `ToolNotFound` / `MCPToolAdapter` 失败

```bash
# 1) 看具体 tool 名
grep "ToolNotFound\|MCPToolAdapter" data/logs/app.log | tail -10

# 2) 检查 ToolRegistry 是否含该 tool
curl -s http://localhost:8000/api/tools-skills | jq '.tools[].name' | grep <tool_name>

# 3) MCP server 是不是没连
curl -s http://localhost:8000/api/mcp/status | jq '.servers[] | select(.status != "connected")'
```

**修复**:
```bash
# a) MCP server 没连上 → 见 §4.1
# b) Tool 名字拼错 → 改 builtin.py allowed_tools 或 Skill 内部 hardcode
# c) ToolRegistry 被 reset → 重启服务(_register_all_tools_and_skills 会重新注册)
docker restart green-agent
```

### 4.4 症状:`pytest` 挂了(P10/P11 相关)

```bash
# 1) 看具体哪个测试挂
pytest tests/test_p6s15_tools_skills.py tests/test_p6s16_mcp_integration.py \
       tests/test_mcp_registry.py tests/test_mcp_streamable.py \
       tests/test_skills_compliance.py -v 2>&1 | tail -50

# 2) Skill 合规测试
pytest tests/test_skills_compliance.py::test_skill_metadata_compliance -v
# 期望:3 passed(每个 Skill 1 个)

# 3) MCP stdio 测试
pytest tests/test_mcp_registry.py -v
# 期望:连接 mock_server 成功,list_tools 返 3 个

# 4) MCP streamable-http 测试
pytest tests/test_mcp_streamable.py -v
# 期望:连接本地 mock HTTP server(端口 8765)成功

# 5) 看 mock HTTP server 是否还在
pgrep -fa "mock_http_mcp_server" | head -3
# 如果没,手动起:
python scripts/mock_http_mcp_server.py --port 8765 &
```

**修复**:
```bash
# a) mock_http_mcp_server 没起
python scripts/mock_http_mcp_server.py --port 8765 &
sleep 1
curl -X POST http://127.0.0.1:8765/mcp -H "Content-Type: application/json" \
     -d '{"jsonrpc":"2.0","id":1,"method":"ping"}'

# b) 端口被占
ss -tlnp | grep 8765
# kill 占用进程 或 改 mock HTTP server 端口 + 改 config/mcp_servers.yaml

# c) Skill 合规校验失败(name 不匹配 ^[a-z0-9_-]+$ / description 太长 / when_to_use 空)
pytest tests/test_skills_compliance.py -v --tb=short
# 修 builtin.py 里对应字段

# d) MCP 子进程超时(Linux 资源紧)
pytest tests/test_mcp_registry.py -v --timeout=60
# 提高 connect_timeout_s(MCPClientConfig)
```

### 4.5 症状:`/api/mcp/status` 返 `servers_count=0`

```bash
# 1) 看是否 load_config 失败
grep "MCPRegistry.*config\|加载配置\|解析失败" data/logs/app.log | tail -10

# 2) 检查 yaml 文件
docker exec green-agent cat /app/config/mcp_servers.yaml | head -5
# 期望:mcp_servers: 字段存在

# 3) yaml 语法错误(常见:缩进 / 中文标点)
docker exec green-agent python -c "
import yaml
print(yaml.safe_load(open('/app/config/mcp_servers.yaml').read()) is not None)
"

# 4) 配置文件路径不对
grep -r "mcp_servers.yaml\|MCPRegistry.*load_config" src/server/ | head -5
# 期望:config/mcp_servers.yaml(相对 cwd)
```

**修复**:
```bash
# a) yaml 语法错
vim config/mcp_servers.yaml    # 修缩进 / 中文改英文冒号等
docker restart green-agent

# b) 路径不对(容器内 cwd 不是 /app)
docker exec green-agent ls /app/config/mcp_servers.yaml
# 改 _start_mcp_registry(config_path=...) 或 docker WORKDIR

# c) 所有 server 都 disabled(enable 字段全 false)
grep "enabled:" config/mcp_servers.yaml
# 把需要的改 true
```

### 4.6 症状:HTTP MCP 401 / 403

```bash
# 1) 看哪个 server
grep "HTTP 401\|HTTP 403\|Unauthorized" data/logs/app.log | tail -10

# 2) 检查 config 里 headers / Authorization
grep -A3 "Authorization\|Bearer" config/mcp_servers.yaml

# 3) token 是否过期
docker exec green-agent bash -c 'echo $NOTION_TOKEN' | head -c 20
# 注意:不要 echo 完整 token,前 20 字符够识别即可
```

**修复**:
```bash
# a) token 过期
# 在 config 改 headers.Authorization,或更新 .env → docker restart

# b) Bearer 格式错
# headers: { Authorization: "Bearer <token>" }  注意 Bearer 后空格

# c) Origin 被拒(MCP Streamable HTTP 强制 Origin 头校验)
# 改 config 里 origin 字段,或 server 端白名单

# d) 403 = permissions 不够
# 看 server 端权限配置(scope / ACL)
```

---

## 5. 应急操作(无需重启)

### 5.1 关闭某个 Skill(避免误触发)

```python
# 临时从 SkillExecutor 移除(进程内有效,重启失效)
docker exec green-agent python -c "
from agent.skills import get_skill_executor
import agent.skills.builtin
ex = get_skill_executor()
ex._skills.pop('policy_query', None)
print('after:', ex.list_all())
"
```

### 5.2 关闭某个 MCP server(避免反复失败)

```yaml
# config/mcp_servers.yaml
mcp_servers:
  - name: 故障_server
    enabled: false   # 改后重启
```

或**临时**直接 disable 某个 client(MCPRegistry._started=True 后改 dict):

```bash
docker exec green-agent python -c "
from mcp import get_mcp_registry
reg = get_mcp_registry()
# 把已连的 client 立即断开
if 'mock_server' in reg._clients:
    reg._clients['mock_server'].disconnect()
    reg._server_info['mock_server'].status = 'disabled'
print('after:', reg.status())
"
```

### 5.3 强制重写所有 SKILL.md(无需重启)

```bash
docker exec green-agent python -c "
from agent.skills import get_skill_executor
import agent.skills.builtin
ex = get_skill_executor()
for name in ex.list_all():
    s = ex.get(name)
    path = s.write_skill_md()
    print('wrote:', path)
"
# 期望:3 行 wrote:
```

### 5.4 手动重连 MCP server(某 server 状态卡在 connecting)

```bash
docker exec green-agent python -c "
from mcp import get_mcp_registry
reg = get_mcp_registry()
name = 'mock_server'
client = reg._clients.get(name)
if client:
    client.disconnect()
    ok = client.connect()
    print('reconnect:', ok, client.error)
"
# 期望:reconnect: True None
```

### 5.5 强制 Skill 走 mock(LLM 不可用时)

```yaml
# config/settings.yaml
llm:
  use_mock: true    # LLM_MOCK 走本地桩,不调外部
```

```bash
docker exec green-agent sed -i 's/use_mock: false/use_mock: true/' /app/config/settings.yaml
docker exec green-agent kill -HUP 1 || docker restart green-agent
```

### 5.6 临时禁用 MCP 整个子系统

```bash
# 1) 直接把 config 备份成空
docker exec green-agent cp /app/config/mcp_servers.yaml /app/config/mcp_servers.yaml.bak
docker exec green-agent bash -c 'echo "" > /app/config/mcp_servers.yaml'
docker restart green-agent

# 2) 或者改 lifecycle 跳过 _start_mcp_registry(代码改动,需 PR)
# 见 src/server/lifecycle.py 注释掉 _start_mcp_registry()
```

### 5.7 手动跑 Skill 触发评估(测试回归)

```bash
USE_REAL_LLM=1 python scripts/eval_skills.py
# 期望:trigger_accuracy ≥ 0.90 → exit 0
# 报告:data/eval_report_skills.md
```

---

## 6. 维护任务

### 6.1 每周(周一上午)

```bash
# 1) MCP server 状态体检
curl -s http://localhost:8000/api/mcp/status | \
  jq '.servers[] | {name, status, tools_count, error}'

# 2) Skill 注册数体检
curl -s http://localhost:8000/api/tools-skills | \
  jq '{tools_count, skills_count, skills: [.skills[].name]}'
# 期望:tools_count = 内置 + MCP tool 数,skills_count = 3

# 3) SKILL.md 文件数体检
EXPECTED=$(curl -s http://localhost:8000/api/tools-skills | jq '.skills_count')
ACTUAL=$(ls /opt/green-agent/.claude/skills/*/SKILL.md 2>/dev/null | wc -l)
[ "$EXPECTED" = "$ACTUAL" ] && echo "ok" || echo "MISSING: $EXPECTED != $ACTUAL"

# 4) MCP 后台线程存活
ps -ef | grep "mcp-registry" | grep -v grep | head -2

# 5) stdio 子进程存活
pgrep -fa "python.*mcp_mock_server" | wc -l
```

### 6.2 每月(1 号凌晨)

```bash
# 1) 跑 Skill / MCP 全量回归
pytest tests/test_p6s15_tools_skills.py tests/test_p6s16_mcp_integration.py \
       tests/test_mcp_registry.py tests/test_mcp_streamable.py \
       tests/test_skills_compliance.py -v

# 2) 跑 Skill 触发准确率评估
USE_REAL_LLM=1 python scripts/eval_skills.py
# 期望:trigger_accuracy ≥ 0.90

# 3) MCP 健康检查(每个 enabled server)
python -c "
from mcp import get_mcp_registry
import time
reg = get_mcp_registry()
for name, client in reg._clients.items():
    if hasattr(client, '_connected'):
        print(name, 'connected=', client._connected, 'last_err=', getattr(client, '_error', None))
"

# 4) SKILL.md 时效性检查(版本号是否与 builtin.py 一致)
python -c "
import re, pathlib
from agent.skills import get_skill_executor
import agent.skills.builtin
ex = get_skill_executor()
for n in ex.list_all():
    s = ex.get(n)
    md = pathlib.Path(f'.claude/skills/{n}/SKILL.md')
    if md.exists():
        text = md.read_text()
        ver = re.search(r'version: (.+)', text)
        print(n, 'code=', s.version, 'md=', ver.group(1) if ver else '?')
"

# 5) 备份 Skill 配置(MCP yaml + SKILL.md 目录)
tar czf /backup/skills_$(date +%Y%m%d).tgz config/mcp_servers.yaml .claude/skills/
```

### 6.3 每季度

```bash
# 1) MCP 协议规范升级检查(2025-11-25 → 2026-??)
# 看 https://modelcontextprotocol.io/specification 看 latest version
# 若 protocolVersion 字段需更新 → 改 src/mcp/client.py / streamable_client.py

# 2) Anthropic Skills 规范变更检查
# https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview
# 若新增必填字段 → 改 Skill.validate() + builtin.py

# 3) 真 Skill 触发评测(CI gate)
USE_REAL_LLM=1 python scripts/eval_skills.py
# 报告:data/eval_report_skills.md

# 4) 误判案例人工 review
cat data/eval_report_skills.md | grep -A5 "未通过明细"

# 5) MCP server 列表 review(增加 / 删除 / 改 transport)
# config/mcp_servers.yaml 上 git diff + review
```

### 6.4 MCP server 添加流程(标准操作)

```bash
# 1) 编辑 config/mcp_servers.yaml(加一条)
cat >> config/mcp_servers.yaml <<'EOF'
  - name: my_new_server
    description: 新 MCP server(说明用途)
    enabled: false   # 先 false,验证后再开
    transport: stdio
    command: python
    args:
      - path/to/server.py
    env:
      MY_KEY: your_key_here
    connect_timeout_s: 10.0
    request_timeout_s: 30.0
EOF

# 2) 本地验证(stdio 直连)
python path/to/server.py < /dev/null &
SERVER_PID=$!
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | \
  python path/to/server.py
kill $SERVER_PID 2>/dev/null

# 3) 启服务,验证 /api/mcp/status
docker restart green-agent
curl -s http://localhost:8000/api/mcp/status | jq '.servers[] | select(.name=="my_new_server")'

# 4) 改 enabled=true + PR review + 合并
vim config/mcp_servers.yaml   # enabled: true
docker restart green-agent
```

---

## 7. 升级 / 回滚

### 7.1 MCP 协议版本升级

```bash
# 1) 看代码里 protocolVersion 常量
grep -r "protocolVersion" src/mcp/ | head -5
# 当前 client: 2024-11-05;streamable: 2025-11-25

# 2) 备份
cp src/mcp/client.py src/mcp/client.py.bak.$(date +%Y%m%d)
cp src/mcp/streamable_client.py src/mcp/streamable_client.py.bak.$(date +%Y%m%d)

# 3) 改版本号(若有 breaking change)
# 改 src/mcp/client.py / streamable_client.py 的 PROTOCOL_VERSION

# 4) 跑回归
pytest tests/test_mcp_registry.py tests/test_mcp_streamable.py tests/test_p6s16_mcp_integration.py -v

# 5) 重启 + 监控 30min
docker restart green-agent
curl -s http://localhost:8000/api/mcp/status | jq '.servers_count'
grep "MCPRegistry" data/logs/app.log | tail -20
```

**回滚**:
```bash
cp src/mcp/client.py.bak.<date> src/mcp/client.py
cp src/mcp/streamable_client.py.bak.<date> src/mcp/streamable_client.py
docker restart green-agent
```

### 7.2 Anthropic Skills 规范升级

```bash
# 1) 看代码里校验规则
grep -E "_NAME_RE|_MAX_NAME_LEN|_RESERVED_NAME" src/agent/skills/skill.py

# 2) 备份 builtin.py(若新增内置 Skill)
cp src/agent/skills/builtin.py src/agent/skills/builtin.py.bak.$(date +%Y%m%d)

# 3) 改 skill.py::validate()(若规范新增字段)

# 4) 跑合规测试
pytest tests/test_skills_compliance.py -v

# 5) 重生 SKILL.md
docker exec green-agent python -c "
from agent.skills import get_skill_executor
import agent.skills.builtin
ex = get_skill_executor()
for n in ex.list_all():
    s = ex.get(n)
    s.write_skill_md()
"

# 6) 重启
docker restart green-agent
```

### 7.3 MCP server 列表变更(无须重启 / 需 reload)

`config/mcp_servers.yaml` 改动后:

```bash
# 必须重启:启动时 load_config
docker exec green-agent kill -HUP 1 || docker restart green-agent

# 若接 SIGHUP reload(看 src/main.py 是否实现)
docker exec green-agent kill -HUP 1
curl -s http://localhost:8000/api/mcp/status | jq '.servers_count'
# 期望反映最新配置
```

### 7.4 代码变更

```
branch: feat/p10-skills-* / feat/p11-mcp-http-*
  ↓
PR + 2 review (SRE + agent owner)
  ↓
CI 必须全绿:
  - tests/test_skills_compliance.py        (3 case)
  - tests/test_p6s15_tools_skills.py      (Skill 注册 + schema)
  - tests/test_p6s16_mcp_integration.py   (stdio 端到端)
  - tests/test_mcp_registry.py            (Registry 单例 + connect_all)
  - tests/test_mcp_streamable.py          (HTTP 端到端)
  - scripts/eval_skills.py exit 0(trigger_accuracy ≥ 0.90)
  ↓
merge to main
  ↓
image tag v2.x.y → K8s rolling update
```

### 7.5 数据备份 / 恢复

```bash
# 备份
tar czf /backup/skills_$(date +%Y%m%d).tgz .claude/skills/ config/mcp_servers.yaml

# 恢复(单 Skill)
tar xzf /backup/skills_20260718.tgz -C / .claude/skills/low_carbon_travel/SKILL.md
docker restart green-agent

# 整库恢复(灾难场景)
tar xzf /backup/skills_20260718.tgz -C /
docker restart green-agent
```

---

## 8. 联系 / 升级流程

### 8.1 责任分工

| 角色 | 联系方式 | 职责 |
|---|---|---|
| **SRE oncall** | PagerDuty `green-agent-sre` | 7x24 故障响应,MCP 全断 / Skill 不可用 / 后台线程死 |
| **Agent owner** | @agent-owner | Skills / ToolRegistry / Skill 触发准确率回归 |
| **MCP owner** | @mcp-owner | MCP server 接入 / 协议升级 / Transport 切换 |
| **Dev owner** | @backend-owner | 代码改动 / 缺陷修复 / 性能调优 |
| **Security** | @sec-owner | MCP token 轮换 / Origin 白名单 / Origin 校验 |

### 8.2 故障升级路径

```
L1: SRE oncall → 5min 内 acknowledge
    ├─ 可自助处理 → 关 server / 改 enabled / 重启 / 重写 SKILL.md → 30 min
    └─ 需 Agent 协助 → 拉 @agent-owner

L2: @agent-owner → 评估 Skill / MCP 兼容性 → 必要时改 builtin.py + 发 hotfix
    └─ 仍不解 → 拉 @mcp-owner

L3: 拉 infra 升级 / 协议规范变更 → @sec-owner(若涉及 token / Origin)
    └─ P0 业务断流 → 写入 postmortem 模板,24h 内复盘
```

### 8.3 报告产物

| 触发 | 产出 |
|---|---|
| MCP 全断 | Slack `data-incident` + 引用本文 §4.1 |
| Skill 触发准确率 < 80% 持续 30min | Slack `agent-perf` + `data/eval_report_skills.md` |
| 后台 mcp-registry 线程死 | Slack `data-runtime` + `ps -ef` 输出 |
| MCP HTTP 401 burst | Notion 安全告警 + 检查 token |
| SKILL.md 写入失败 | Slack `data-disk` + 检查 `.claude/` 权限 |
| 协议规范 breaking change | postmortem(归档到 `docs/operations/postmortem-YYYYMMDD.md`) |

### 8.4 关键链接(模板)

- **Prometheus 规则**:`/etc/prometheus/rules/skills_mcp.yml`(见 §3.1)
- **Grafana Dashboard**:`dashboard/skills-mcp-overview.json`
- **Postmortem 模板**:`docs/operations/postmortem-template.md`
- **变更管理**:`docs/operations/CHANGE_LOG.md`(每次改 mcp_servers.yaml / 加 Skill / 协议升级都登记)
- **Git 仓库**:`https://github.com/<org>/green-agent`
- **镜像仓库**:`registry.example.com/green-agent:v2.x.y`
- **生产 K8s**:`kubectl -n green-agent get deploy green-agent`
- **MCP 协议规范**:<https://modelcontextprotocol.io/specification>
- **Anthropic Skills 规范**:<https://docs.claude.com/en/docs/agents-and-tools/agent-skills/overview>

---

## 附录 A:关键文件路径速查

```text
<PROJECT_ROOT>/
├── config/
│   └── mcp_servers.yaml            # MCP server 配置(transport 分发)
├── src/
│   ├── agent/skills/
│   │   ├── skill.py                # Skill 基类 + SkillExecutor + write_skill_md
│   │   ├── builtin.py              # LowCarbonTravelSkill / PolicyQuerySkill / ProfileUpdateSkill
│   │   └── __init__.py             # get_skill_executor 单例
│   ├── mcp/
│   │   ├── client.py               # MCPClient(stdio)
│   │   ├── streamable_client.py    # StreamableHTTPClient(P11.B)
│   │   ├── adapter.py              # MCPToolAdapter(包成 BaseTool)
│   │   ├── registry.py             # MCPRegistry 单例 + load_config + connect_all
│   │   ├── server.py               # MCPServer(本地 server 暴露)
│   │   └── __init__.py             # 公共导出
│   └── server/
│       ├── app.py                  # _register_all_tools_and_skills / _start_mcp_registry
│       ├── lifecycle.py            # init_app() 第 3、4 步
│       └── routers/system.py       # /api/tools-skills + /api/mcp/status
├── scripts/
│   ├── mcp_mock_server.py          # stdio mock(echo/weather/carbon)
│   ├── mock_http_mcp_server.py     # HTTP mock(127.0.0.1:8765/mcp)
│   └── eval_skills.py              # trigger_accuracy 评估(gate)
├── .claude/skills/                 # SKILL.md 输出目录(Anthropic 规范)
│   ├── low_carbon_travel/SKILL.md
│   ├── policy_query/SKILL.md
│   └── profile_update/SKILL.md
├── tests/
│   ├── test_skills_compliance.py   # Skill 元数据合规校验
│   ├── test_p6s15_tools_skills.py  # Skill 注册 + schema
│   ├── test_p6s16_mcp_integration.py  # stdio 端到端
│   ├── test_mcp_registry.py        # Registry 单例 + connect_all
│   └── test_mcp_streamable.py      # HTTP 端到端
└── docs/operations/
    └── p10-skills-mcp.md           # 本文件
```

## 附录 B:一行命令速查

```bash
# 健康
curl -s http://localhost:8000/api/tools-skills | jq '.skills_count, .skills[].name'
curl -s http://localhost:8000/api/mcp/status | jq '.servers_count'
curl -s http://localhost:8000/api/health | jq '.health'

# Skill / MCP 状态
curl -s http://localhost:8000/api/tools-skills | jq '.'
curl -s http://localhost:8000/api/mcp/status | jq '.servers[] | {name, status, tools_count}'

# SKILL.md 文件
ls /opt/green-agent/.claude/skills/*/SKILL.md 2>/dev/null | wc -l

# 后台线程
ps -ef | grep "mcp-registry" | grep -v grep | head -2

# stdio 子进程
pgrep -fa "python.*mcp_mock_server" | head -3

# 最近 24h 错误日志
grep -iE "MCPRegistry|MCPClient|SkillExecutor.*Error|skill_trigger" data/logs/app.log | tail -50

# 重写 SKILL.md
docker exec green-agent python -c "
from agent.skills import get_skill_executor
import agent.skills.builtin
for n in get_skill_executor().list_all():
    print(get_skill_executor().get(n).write_skill_md())
"

# 重连 MCP server
docker exec green-agent python -c "
from mcp import get_mcp_registry
reg = get_mcp_registry()
name = 'mock_server'
c = reg._clients.get(name)
if c: c.disconnect(); print('reconnect:', c.connect())
"

# 评估
USE_REAL_LLM=1 python scripts/eval_skills.py

# 测试
pytest tests/test_p6s15_tools_skills.py tests/test_p6s16_mcp_integration.py \
       tests/test_mcp_registry.py tests/test_mcp_streamable.py \
       tests/test_skills_compliance.py -v

# 关 MCP(运行时)
docker exec green-agent cp /app/config/mcp_servers.yaml /tmp/mcp_servers.yaml.bak
docker exec green-agent bash -c 'echo "" > /app/config/mcp_servers.yaml'
docker restart green-agent
# 恢复:
docker exec green-agent cp /tmp/mcp_servers.yaml.bak /app/config/mcp_servers.yaml
docker restart green-agent
```

---

**附**:本手册被 `docs/RUNBOOK.md` 引用(场景 3 后台线程死 + 场景 5 配置启动失败都可能波及 MCP/ Skills);`docs/SECURITY.md` §3 密钥管理涉及 MCP server 自带的 token / Authorization header 轮换策略(每 90 天强轮,失效期间 server 走 disabled 路径)。所有 Skill / MCP 操作经 `data/logs/app.log`(JSON 行)可追溯,grep `[MCPRegistry]` / `[MCPClient]` / `[Skill]` 可聚合引擎分布。