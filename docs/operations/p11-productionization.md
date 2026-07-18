# P11.产品化 运维手册 — 给运维 / SRE

> 适用对象:值班 SRE、运维、发布负责人。
> 读完之后能回答:**P11(CI / Skills 评估 / 真实 MCP)在生产环境长什么样 / 盯哪些指标 / 什么时候告警 / 挂了怎么排 / 怎么应急 / 怎么升级回滚**。
>
> 姊妹篇:
> - `docs/learning/p11-productionization.md` — 给开发/实习生的原理入门(CI/评估/MCP 怎么搭起来)
> - `docs/operations/p11-real-mcp.md` — MCP server 接入的 YAML schema + 排错清单
> - `docs/RUNBOOK.md` / `docs/DEPLOYMENT_RUNBOOK.md` — 部署与通用故障场景

---

## 1. P11 在生产环境的形态

P11 有三个模块,**它们不是运行时的常驻服务,而是"发布关卡 + 可选能力"**。搞清楚这点是运维的第一课:

| 模块 | 生产形态 | 常驻? | 挂了影响面 |
|---|---|---|---|
| **P11.A — Linux CI** | GitHub Actions,PR / push 时触发 | 否(按事件跑) | 挡发布,不影响线上服务 |
| **P11.B — Skills 评估** | CI 里的一个 gate（`scripts/eval_skills.py`），也可离线跑 | 否 | 挡发布;线上 Skill 触发质量的"晴雨表" |
| **P11.C — 真实 MCP** | 运行时可选能力，`config/mcp_servers.yaml` 里 `enabled: true` 才连 | 是(仅当启用) | 只影响用到该 MCP 工具的对话,默认全关不影响主链路 |

### 1.1 P11.A — CI(发布关卡)

- 定义:`.github/workflows/ci.yml`,跑在 `ubuntu-latest` + Python 3.13。
- 两个 Job 串联:`build-and-test`(单测 + live-server 测试 + ruff)→ `docker-build`(build 镜像 + 起容器 + smoke `/api/ready` `/api/health` `/api/chat`)。`docker-build` 用 `needs: build-and-test`,前者绿了才跑。
- **全程 `LLM_MOCK=true` + `USE_MOCK_LLM=true`**:不碰真实 API key、不消耗额度、不受第三方限流影响。
- `concurrency.cancel-in-progress: true`:同一分支新 push 会取消旧 run。
- **红 PR 不许合**是唯一硬约束。CI 与线上服务解耦——CI 挂了线上照常跑,但新版本进不去。

```bash
# 看当前分支 CI 状态
gh run list --branch master --limit 5
# 看最近一次 run 的详情
gh run view --log-failed
```

### 1.2 P11.B — Skills 评估(触发质量 gate)

- 脚本:`scripts/eval_skills.py`,题库:`tests/eval/skills_golden_set.jsonl`(当前 138 条,9+ 类目,中英双语)。
- 阈值常量:`THRESHOLD_TRIGGER = 0.90`(`trigger_accuracy < 0.90` → `exit 1` → CI 红)。
- 产物:`data/skills_eval_report.md`(按类目 + Skill 拆分 + 趋势)、`data/skills_eval_trend.json`(历史分数,给"涨/跌"提供 baseline)。

```bash
# 离线跑一次(约 5s,不需要起服务)
python scripts/eval_skills.py
echo "exit=$?"   # 0=达标 1=不达标
# 看报告
cat data/skills_eval_report.md
```

### 1.3 P11.C — 真实 MCP(运行时可选能力)

- 配置:`config/mcp_servers.yaml`,GitHub / Notion 模板默认 `enabled: false`。
- token 用 `${GITHUB_TOKEN}` 占位符,**真实值只在 `.env` / K8s Secret / Vault**,绝不入 yaml。
- 启动时 `MCPRegistry` 展开占位符 + 连接 `enabled: true` 的 server,包装成本地工具供 `chat_enhanced` 调用。
- 运行时状态查询:`GET /api/mcp/status`(返回每个 server 的 `status` / `tools_count` / `connected_at`)。

```bash
# 线上查 MCP 连接态(prod 换成实际域名)
curl -s http://localhost:8000/api/mcp/status | python -m json.tool
```

---

## 2. 关键指标(KPI)

盯这三个核心 + 若干辅助。**核心指标越过阈值就该有人看。**

| 指标 | 采集来源 | 目标 | 黄色(关注) | 红色(告警) |
|---|---|---|---|---|
| **CI 通过率**(近 20 次 run) | `gh run list` / Actions API | ≥ 95% | 85–95% | < 85% |
| **CI 时长**(P95) | Actions run duration | < 15 min | 15–22 min | > 22 min(接近 25min timeout) |
| **Skills trigger_accuracy** | `data/skills_eval_report.md` | ≥ 0.95 | 0.90–0.95 | < 0.90（CI 直接卡） |
| **Skills fallback_rate** | 同上 | < 0.15 | 0.15–0.25 | > 0.25(太多问题没命中 Skill) |
| **Skills false_positive_rate** | 同上 | 0 | > 0 | > 0.05（误触发） |
| **MCP 连接成功率** | `/api/mcp/status` `status==connected` / enabled 总数 | 100% | — | < 100%(有 enabled server 连不上) |
| **MCP tools_count** | `/api/mcp/status` | > 0(每个 connected server) | — | 0(连上了但没工具 = 权限问题) |
| **Docker smoke 通过率** | `docker-build` job 结果 | 100% | — | 任一 smoke 端点非 200 |

### 2.1 一条命令拉三大核心指标

```bash
# CI 通过率(近 20 次)
gh run list --branch master --limit 20 --json conclusion \
  | python -c "import sys,json; r=json.load(sys.stdin); ok=sum(1 for x in r if x['conclusion']=='success'); print(f'CI pass rate: {ok}/{len(r)} = {ok/len(r):.0%}')"

# Skills trigger_accuracy(离线)
python scripts/eval_skills.py >/dev/null 2>&1; grep -m1 trigger_accuracy data/skills_eval_report.md

# MCP 连接成功率
curl -s http://localhost:8000/api/mcp/status \
  | python -c "import sys,json; d=json.load(sys.stdin); s=d.get('servers',d); print(s)"
```

---

## 3. 告警规则

以下规则可挂到 Prometheus / Grafana / 定时脚本 + 企业微信/钉钉/PagerDuty。**每条给出触发条件 + 严重级 + 首要动作。**

| 规则 | 触发条件 | 级别 | 首要动作 |
|---|---|---|---|
| **A1 CI 连续失败** | `master` 上连续 ≥ 2 次 run `conclusion=failure` | P1 | 冻结合并,查 §5.1 |
| **A2 CI 通过率跌破线** | 近 20 次 run pass rate < 85% | P2 | 排查 flaky 测试 / runner 资源 |
| **A3 CI 超时逼近** | run duration > 22 min(timeout 25) | P3 | 查是否 PaddleOCR 未被 `-k "not paddle"` 排除 / 依赖膨胀 |
| **A4 Skills 触发不达标** | `trigger_accuracy < 0.90` | P1(阻断发布) | 查 §5.2,回滚 golden set / Skill 改动 |
| **A5 Skills fallback 飙高** | `fallback_rate > 0.25` | P2 | 检查是否漏挂 Skill / 关键词失配 |
| **A6 Skills 误触发** | `false_positive_rate > 0.05` | P2 | 检查新 Skill 抢答旧 Skill 的题 |
| **A7 MCP server 掉线** | 某 `enabled` server `status != connected` 持续 > 5 min | P2 | 查 §5.3(token / 网络 / 限流) |
| **A8 MCP 工具数归零** | connected 但 `tools_count == 0` | P3 | 权限不足,重签 token |
| **A9 Docker smoke 失败** | `docker-build` job smoke 任一非 200 | P1(阻断发布) | 查 §5.4 |
| **A10 占位符未展开** | log 出现原样 `${...}` token | P2 | env 未注入,查 §5.5 |

### 3.1 告警脚本骨架(cron 每 10 分钟)

```bash
#!/usr/bin/env bash
# scripts/ops_p11_alert.sh — 挂 crontab: 7,17,27,37,47,57 * * * *
set -euo pipefail
BASE="${AGENT_URL:-http://localhost:8000}"

# A7/A8 MCP 掉线
bad=$(curl -sf "$BASE/api/mcp/status" \
  | python -c "import sys,json; d=json.load(sys.stdin); s=d.get('servers',[]); \
print(sum(1 for x in s if x.get('status')=='connected' and x.get('tools_count',0)==0 or x.get('status') not in ('connected','disabled')))" 2>/dev/null || echo "ERR")
[ "$bad" != "0" ] && echo "[ALERT A7/A8] MCP 异常 server 数=$bad" # → 推送告警
```

---

## 4. 常见故障 + 排查(5 个)

### 5.1 CI 挂了(build-and-test 或 docker-build 红)

**症状**:PR 打红叉,`gh run list` 显示 `failure`。

```bash
# 1) 定位哪个 job / step 挂了
gh run view <run-id> --log-failed | tail -80
# 2) 下载 pytest 日志 artifact(CI always 上传)
gh run download <run-id> -n pytest-logs
tail -60 pytest-main.log pytest-live.log
```

**高频根因与处置**:
- **Linux/Windows 差异**:`os.path.join` 拼错分隔符、大小写敏感文件名 → 本地 `bash scripts/ci_smoke.sh` 复现(它在 Docker/Linux 内跑)。
- **PaddleOCR/Paddle OOM**:CI runner 只有 ~14GB。确认测试仍被 `-k "not paddle and not paddleocr"` 排除;`ci.yml` 的 "Free disk space" step 是否被误删。
- **flaky live-server 测试**:`Run targeted live-server tests` step 允许部分 skip(`|| echo ...`),若整段挂,查 `LLM_MOCK=true` 是否生效。
- **依赖装不上**:`pip install` step 失败 → 查 `requirements*.txt` 是否引入了 Linux 装不了的包。

**处置**:红 PR 一律不合;主干红触发 A1,冻结合并 + 优先修主干或 revert 引入 commit(见 §7)。

### 5.2 Skills 触发不准(trigger_accuracy < 0.90)

**症状**:CI `Skills trigger eval` step exit 1,或离线跑报告 PASS→FAIL。

```bash
# 1) 跑一遍看总分 + 哪个类目掉分
python scripts/eval_skills.py; cat data/skills_eval_report.md
# 2) 跟上次 baseline 比,定位是"涨/跌"
cat data/skills_eval_trend.json | python -m json.tool | tail -30
```

**高频根因**:
- **新加 Skill 抢答**:新 Skill 关键词太宽,把旧 Skill 的题答错(看 `false_positive_rate` + 按 Skill 拆分表哪个 coverage 掉)。
- **golden set 加了难题**:新追加的 query 启发式识别不出 → 调 `scripts/eval_skills.py` 里 `TRAVEL_STRONG_ZH` / `POLICY_STRONG_EN` 等强信号字典。
- **Skill 改名没同步**:`expected_skill` 找不到对应类 → `KeyError`。Skill 改名 = builtin.py + golden set + SKILL.md 三处一起改。

**处置**:发布前 gate,不达标就**不发**;定位到是 golden set 问题还是 Skill 问题后,回退对应改动或调字典直到 ≥ 0.90。

### 5.3 MCP 连接失败(enabled server status != connected)

**症状**:`/api/mcp/status` 某 server `status: error` 或 `connecting` 卡住;用到该工具的对话报工具不可用。

```bash
# 1) 看状态 + 错误
curl -s http://localhost:8000/api/mcp/status | python -m json.tool
# 2) 抓日志(JSON,带 trace_id)
grep -i mcp data/logs/app.log | tail -40
grep -i mcp data/logs/error.log | tail -20
# 3) 手测端点可达性(GitHub 示例)
curl -I https://api.githubcopilot.com/mcp/
```

**高频根因与对照**（详见 `docs/operations/p11-real-mcp.md` §5):
- `401 Unauthorized` → token 失效/格式错(`ghp_` / `secret_` 前缀),重签。
- `ConnectError` → 网络/代理,查 `HTTPS_PROXY`、防火墙。
- `tools_count: 0` → 连上但权限不足,重签带足权限的 token(触发 A8)。
- `Origin 403` → server 端 Origin 校验,补 `origin` / `allowed_origins` 字段。
- 启动 hang → stdio server 卡 initialize,加 `connect_timeout_s: 5.0`。

**处置**:MCP 是可选能力——紧急时把该 server `enabled: false` 重启,主链路不受影响(见 §6)。

### 5.4 Docker smoke 失败(容器起不来 / 端点非 200)

**症状**:`docker-build` job 在 "Wait for boot" 或 smoke step 挂;或本地 `ci_smoke.sh` 卡在 "Waiting for service to be ready"。

```bash
# 本地复现整条 CI smoke
bash scripts/ci_smoke.sh
# 换端口(8000 被占时)
HOST_PORT=8001 bash scripts/ci_smoke.sh
# 手动排查
docker ps -a | grep green-agent
docker logs green-agent | tail -80        # 看启动异常
docker exec green-agent curl -sf http://localhost:8000/api/ready
```

**高频根因**:
- **冷启动慢**:ChromaDB 首次加载 + PaddleOCR 懒初始化,CI 给了 40s。本地机器慢可等更久。
- **端口占用**:换 `HOST_PORT`。
- **镜像没重 build**:`docker build . -t green-agent:test` 后重试。
- **ready 一直 200 不了**:进容器查 DB/Chroma 是否初始化失败(见 `docs/RUNBOOK.md` ChromaDB 损坏场景)。

### 5.5 环境变量占位符未展开(`${GITHUB_TOKEN}` 原样出现)

**症状**:日志里 MCP header 显示字面 `${GITHUB_TOKEN}`;MCP 401。

```bash
# 1) 确认 env 真的注入了进程
echo "${GITHUB_TOKEN:-NOT_SET}"
# 2) .env 格式检查(等号后不能有空格/引号)
grep GITHUB_TOKEN .env
# 3) 启动前显式注入再拉服务
set -a; source .env; set +a
# 4) 重启(env 在 fork 时继承)
```

**关键点**:`MCPRegistry._expand_env()` 找不到变量时**保留 `${VAR}` 原样、不静默 fail**,所以日志出现字面占位符 = 该 env 没设。生产用 K8s Secret / Vault 注入,别依赖 `.env`。

---

## 5. 应急操作

### 6.1 紧急关掉某个 MCP server(不停主服务)

```bash
# 编辑 config/mcp_servers.yaml,把出问题的 server 改 enabled: false
# 然后重启(优雅重启见 6.3)
# 验证:该 server 从 /api/mcp/status 消失或 status=disabled
curl -s http://localhost:8000/api/mcp/status | python -m json.tool
```

### 6.2 冻结合并(CI 主干红时)

```bash
# 保护主干:临时开启 required status checks / 通知全员停止合并
gh api repos/:owner/:repo/branches/master/protection --method PUT ... # 视仓库策略
# 或直接群里喊停 + revert 引入 commit(见 §7.2)
```

### 6.3 优雅重启服务

```bash
# systemd
sudo systemctl restart green-agent && journalctl -u green-agent -f
# docker
docker restart green-agent && docker logs -f green-agent
# 裸进程(SIGTERM graceful,app.py 已处理)
kill -TERM "$(pgrep -f 'python.*main.py')"; sleep 3; (cd src && nohup python main.py &)
```

### 6.4 跳过 Skills gate 强制发布(仅限重大事故)

```bash
# 不推荐。仅当 gate 本身出 bug 且线上急需修复时,临时把 CI step 注释掉
# 或本地跑通后走 hotfix 分支,事后补回 gate + golden set
python scripts/eval_skills.py --threshold 0.0   # 明确记录:临时降阈值
```
> ⚠️ 每次跳过必须开 issue 记录原因 + 补回时间,严禁常态化。

---

## 6. 维护任务

| 周期 | 任务 | 命令 / 动作 |
|---|---|---|
| **每次发布前** | 跑 Skills 评估 + 全量回归 | `python scripts/eval_skills.py && pytest tests/ -k "not paddle and not paddleocr"` |
| **每次发布前** | 本地 Docker smoke | `bash scripts/ci_smoke.sh` |
| **每周** | 看 CI 通过率趋势,清 flaky 测试 | `gh run list --limit 20` |
| **每周** | 检查 MCP server 连接态 + token 到期 | `curl .../api/mcp/status`(GitHub PAT 有有效期) |
| **每月** | 扩/校 golden set,防题库过时 | 追加 `tests/eval/skills_golden_set.jsonl` 后重跑 |
| **每月** | 更新 baseline 趋势 | 确认 `data/skills_eval_trend.json` 记录了最新分 |
| **每季度** | 审计 `.env` / Secret 未泄漏进 git | `git log -p -- config/mcp_servers.yaml \| grep -i token` |
| **依赖更新时** | 重跑 CI 全链路 | push 到测试分支跑一遍 `ci.yml` |
| **runner 升级时** | 确认磁盘清理 step 仍有效 | 看 `Free disk space` step 的 `df -h` 输出 |

---

## 7. 升级 / 回滚

### 7.1 升级(发新版本)

```bash
# 1) 在 feature 分支跑完整 CI(build-and-test + docker-build 全绿)
git push origin feature/xxx
gh run watch                       # 盯到全绿

# 2) 本地三件套自检
python scripts/eval_skills.py                          # trigger_accuracy >= 0.90
pytest tests/ -k "not paddle and not paddleocr" --tb=short
bash scripts/ci_smoke.sh                               # docker smoke PASS

# 3) 合并 → 主干 CI 再绿一次 → 部署
git checkout master && git merge --no-ff feature/xxx
# 4) 部署后远程 smoke(对现成服务)
URL=https://prod.example.com bash scripts/deploy_smoke_test.sh
```

**升级 MCP 配置**(加/改 server):改 `config/mcp_servers.yaml` → 先 `enabled: false` 上线 → 灰度期确认 token/网络 OK → 再 `enabled: true` 重启 → 查 `/api/mcp/status`。

**升级 golden set / 阈值**:调 `THRESHOLD_TRIGGER` 或加题后,先离线 `python scripts/eval_skills.py` 确认过线,再改 CI。

### 7.2 回滚

```bash
# A) 代码回滚(主干红 / 新版本线上异常)
git revert <bad-commit> && git push        # 保留历史,触发 CI 重跑
# 或紧急重置(需强制推,谨慎)
git reset --hard <last-good-commit>

# B) 镜像回滚(docker 部署)
docker pull green-agent:<last-good-sha>     # CI 用 github.sha 打过 tag
docker stop green-agent && docker rm green-agent
docker run -d --name green-agent -p 8000:8000 --env-file .env green-agent:<last-good-sha>
URL=http://localhost:8000 bash scripts/deploy_smoke_test.sh   # 确认回滚后健康

# C) MCP 能力回滚(某 server 上线后出问题)
# config/mcp_servers.yaml 该 server 改回 enabled: false → 重启(§6.3)

# D) golden set / 阈值回滚
git checkout <last-good-commit> -- tests/eval/skills_golden_set.jsonl scripts/eval_skills.py
python scripts/eval_skills.py               # 确认回到达标状态
```

**回滚验证清单**:
1. `/api/ready` + `/api/health` 返 200;
2. `/api/mcp/status` enabled server 全 `connected`;
3. `python scripts/eval_skills.py` exit 0;
4. 关键对话链路(`/api/chat/enhanced`)人工抽测一条。

---

## 附录:一页速查

| 想干啥 | 命令 |
|---|---|
| 看 CI 状态 | `gh run list --branch master --limit 5` |
| 看 CI 失败日志 | `gh run view <id> --log-failed` |
| 本地复刻 CI smoke | `bash scripts/ci_smoke.sh` |
| 部署后远程 smoke | `URL=https://prod bash scripts/deploy_smoke_test.sh` |
| 跑 Skills 评估 | `python scripts/eval_skills.py` |
| 看 Skills 报告 | `cat data/skills_eval_report.md` |
| 看 MCP 连接态 | `curl -s .../api/mcp/status \| python -m json.tool` |
| 关某 MCP server | 改 yaml `enabled: false` + 重启 |
| 优雅重启 | `systemctl restart green-agent` |
| 抓 MCP 日志 | `grep -i mcp data/logs/app.log \| tail -40` |
| 代码回滚 | `git revert <commit>` |
| 镜像回滚 | `docker run ... green-agent:<last-good-sha>` |

---

*版本:v1.0 | 创建于 P11.A/B/C 完成后 | 面向:运维 / SRE | 维护者:SRE 文档工程师*
