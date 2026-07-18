# P11.产品化 学习手册 — 给实习生的 30 分钟入门

> 适用对象:刚看完 P9 / P10 文档的实习生,有 Python 基础 + 一点点 Docker / GitHub Actions 概念即可。
> 阅读时间:约 30 分钟。
> 读完之后能回答:**P11 做了什么 / 为什么做 / 在哪里 / 怎么跑 / 怎么扩**。
>
> 跟 `docs/learning/p11-real-mcp.md` 的区别:那篇是给**最终用户**看的(怎么开 GitHub / Notion MCP),这篇是给**开发同学**看的(CI 流水线 / 评估闭环 / MCP 接入是怎么搭起来的)。

---

## 1. P11 是什么

### 1.1 P11.A — Linux CI(让代码每次改动都能被"自动验一遍")

之前我们的测试主要在 Windows + 同事本机跑。问题是:**"我机器上能跑"≠"生产环境能跑"**。P10.B 加完 Streamable HTTP 后,跨平台问题突然变多 — Linux 下 httpx 的事件循环、Windows 下的 ChromaDB 锁文件、CI runner 上的 OOM,都在本地复现不出来。

P11.A 做三件事:**(1)** 把单测 / ruff lint / Docker 镜像 build / 容器内 smoke 全部串到 GitHub Actions(`.github/workflows/ci.yml`,跑在 `ubuntu-latest`);**(2)** 写一个 `scripts/ci_smoke.sh`,本地一行 `bash scripts/ci_smoke.sh` 就能复刻 CI 的"起容器 → 等 ready → 跑三个端点"流程;**(3)** CI 用 `LLM_MOCK=true` 跑,既不依赖真实 API key 也不消耗额度。从今往后,任何 PR 都得过这个流水线,**红 PR 一律不许合**。

### 1.2 P11.B — Skills 评估扩到 100+ 场景(P10 评估集长大一倍)

P10.C 留了个 golden set(20 来条),trigger_accuracy 阈值是 0.85。P11.B 把这份"考试题"扩到 **100+ 条**,**类目**从 4 类(出行 / 政策 / 画像 / 杂)扩到 **9 类**(加 weather-travel / carbon-calc / language-switch / follow-up / chitchat 等),**中英双语**(TRAVEL_STRONG_EN 等);**CI gate 阈值**也从 0.85 抬到 **0.90**,逼 LLM 必须选对 Skill。

跑 `python scripts/eval_skills.py` 会出 `data/skills_eval_report.md`,里头按类目拆 + 趋势对比,谁扣分一眼能看到。任何新加 Skill 都得过这个"考试",否则 CI 卡掉。

### 1.3 P11.C — 接入真实 MCP(GitHub / Notion 模板就绪)

P10.B 只做了协议(能跟 HTTP MCP server 说话),但 yaml 里全是 mock。P11.C 把 **GitHub 官方 MCP**(`https://api.githubcopilot.com/mcp/`,30+ 工具)和 **Notion 官方 MCP** 模板放进 `config/mcp_servers.yaml`,默认 `enabled: false`(避免无 token 时启动报错)。

关键设计:token 用 `${GITHUB_TOKEN}` 这种**占位符**,**不写进 yaml**(写进 yaml 会被 git diff 抓包)。YAML loader 启动时展开 env,没找到就保留 `${VAR_NAME}` 让你知道哪个变量缺了 — 比静默 fail 友好得多。详细 token 申请 + 启用步骤见姊妹篇 `docs/learning/p11-real-mcp.md`。

---

## 2. 架构图

```mermaid
flowchart TB
    subgraph DEV[本地开发]
        D1[改 builtin.py / yaml / 测试] --> D2[pytest tests/]
        D2 -->|本地通过| D3[git push]
        D2 -->|本地跑 smoke| D4[bash scripts/ci_smoke.sh]
    end

    subgraph CI[GitHub Actions ci.yml]
        C1[Job 1: build-and-test<br/>ubuntu-latest + Python 3.13]
        C2[Quick import smoke<br/>main / LangGraphAgent / server]
        C3[pytest tests/<br/>-k not paddle]
        C4[pytest live-server<br/>mcp + skills + ocr]
        C5[ruff lint src/ tests/]
        C1 --> C2 --> C3 --> C4 --> C5
        C5 -->|需要镜像| DOCKER

        subgraph DOCKER[Job 2: docker-build]
            D5[docker build green-agent:test]
            D6[docker run -d -p 8000]
            D7[wait /api/ready 40s]
            D8[smoke: /api/ready + /api/health + /api/chat]
            D5 --> D6 --> D7 --> D8
        end

        DOCKER -->|全绿| MERGE[允许 merge]
    end

    subgraph EVAL[P11.B Skills 评估闭环]
        E1[tests/eval/skills_golden_set.jsonl<br/>100+ 条,9 类目,中英双语]
        E2[scripts/eval_skills.py<br/>select_skill 启发式打分]
        E3{trigger_accuracy<br/>>= 0.90?}
        E4[data/skills_eval_report.md<br/>按类目 + 趋势]
        E1 --> E2 --> E3
        E3 -->|>= 0.90| E4
        E3 -->|< 0.90| E5[exit 1<br/>PR 卡掉]
    end

    subgraph MCP[P11.C 真实 MCP 接入]
        M1[config/mcp_servers.yaml<br/>enabled=false 模板]
        M2{GITHUB_TOKEN<br/>是否设置?}
        M3[MCPRegistry 启动时<br/>load_config + 展开 ${...}]
        M4[StreamableHTTPClient<br/>POST /mcp + SSE]
        M5[MCPToolAdapter<br/>包装成本地 BaseTool]
        M6[ToolRegistry<br/>chat_enhanced 自动可用]
        M1 --> M2 -->|是| M3
        M3 --> M4 --> M5 --> M6
    end

    D3 -.触发.-> CI
    EVAL -.CI 跑.-> C5
    MCP -.可选接入.-> C6[chat_enhanced]

    style C5 fill:#d4edda
    style E5 fill:#f8d7da
    style M6 fill:#cce5ff
```

**三个模块的关系**:

- **P11.A(CI)** 是大门 — 代码改动必须过,挡掉"本地行 CI 不行"的 PR
- **P11.B(Skills 评估)** 是 Skills 的"期末考" — 加 Skill 必须保持 ≥ 0.90,考试范围已扩到 100+
- **P11.C(真实 MCP)** 是"选修" — 默认关,有 token 想玩再开;不接不影响 CI 通过

---

## 3. 关键文件清单

### 3.1 P11.A — Linux CI

| 文件 | 一句话作用 | 关键步骤 / 函数 |
|---|---|---|
| `.github/workflows/ci.yml` | GitHub Actions 流水线(2 job) | `build-and-test`(pytest + ruff)+ `docker-build`(build + run + smoke 3 件套) |
| `scripts/ci_smoke.sh` | 本地一键 smoke(复刻 CI) | `docker run -d` → `wait /api/ready 60s` → curl 3 个端点 → 自动 stop & rm |
| `scripts/deploy_smoke_test.sh` | 部署后远程 smoke | 配 `URL=https://prod.example.com` 直接对现成服务测 |
| `.github/workflows/test.yml` | 备用 workflow(更轻量,只跑单测) | push-only,不构建镜像 |

**ci.yml 的两个 Job 怎么连**:`build-and-test` 先跑(单测 + ruff),过了才 `needs: build-and-test` 触发 `docker-build`(避免镜像 build 浪费 CI 分钟)。`concurrency.cancel-in-progress` 保证同一 PR 不会被两次 run 同时跑。

### 3.2 P11.B — Skills 评估扩

| 文件 | 一句话作用 | 关键改动 |
|---|---|---|
| `tests/eval/skills_golden_set.jsonl` | 100+ 条 trigger 测试 | 加 `category: weather-travel / carbon-calc / language-switch / chitchat` + 英文样本 |
| `scripts/eval_skills.py` | 评估脚本 + CI gate | `TRAVEL_STRONG_EN` 等双语字典 + `THRESHOLD_TRIGGER = 0.90`(原 0.85) |
| `data/skills_eval_report.md` | 自动生成报告 | 按 category 拆分 + 趋势对比(谁涨谁跌) |
| `data/skills_eval_trend.json` | 历史分数趋势 | 给"这次比上次是涨是跌"提供数据 |

**关键常量**:`THRESHOLD_TRIGGER = 0.90`(P11.B 新阈值),触发准确率 < 0.90 时 `exit 1`,CI 红灯。

### 3.3 P11.C — 真实 MCP

| 文件 | 一句话作用 | 关键类 / 字段 |
|---|---|---|
| `config/mcp_servers.yaml` | MCP server 集中配置 | `github`(Streamable HTTP)+ `notion`(OAuth 模板);`enabled: false` 默认 |
| `src/mcp/streamable_client.py` | Streamable HTTP 客户端 | `StreamableHTTPClient` / `_post_request` / `_sse_loop` |
| `src/mcp/registry.py` | 集中管理所有 MCP client | `MCPRegistry.load_config()` / `_expand_env()`(P11.C 新增) |
| `src/mcp/adapter.py` | 把 MCP tool 包成本地 BaseTool | `MCPToolAdapter._extract_text()` |
| `.env` | 真实 token 存放(git ignore) | `GITHUB_TOKEN=ghp_xxx...` / `NOTION_TOKEN=secret_xxx...` |
| `docs/learning/p11-real-mcp.md` | 姊妹篇(给最终用户) | GitHub PAT 怎么申请 + Notion integration 怎么 share |

**环境变量展开**:`MCPRegistry._expand_env()` 在 load_config 时遍历所有字符串字段,把 `${VAR}` 替换成 `os.environ.get("VAR")`,没找到就保留 `${VAR}`(方便排错)。

---

## 4. 三个核心概念(用比喻)

### 4.1 CI = 餐厅的"出菜检查流水线"

想象你开了一家快餐店,后厨每做一道菜,出餐口都得过一道"出菜检查"——**菜熟没熟、量够不够、摆盘对不对**。客人拿到这道菜之前,谁也别想端走。

GitHub Actions 的 CI 就是这个出菜检查:每次有人 `git push`,系统自动:

1. **拉一个新厨房**(干净的 ubuntu-latest runner,啥都没装)
2. **装锅碗瓢盆**(`pip install -r requirements.txt`)
3. **试炒三道菜**(pytest:单元 + 集成)
4. **试炒需要上灶的菜**(live-server tests,mock 模式)
5. **盖个章**(ruff lint:代码风格)
6. **再起一个外卖档口**(docker build + run)
7. **外卖送达试吃**(`/api/ready` + `/api/health` + `/api/chat`)

任何一步不过,**红灯亮、PR 卡住、谁也别想合并**。好处是:**你不用信任 PR 作者"我本地跑过"**,系统替你验了。

`scripts/ci_smoke.sh` 就是这个流程的**家用版**——你不想 push 之后等 10 分钟才知道挂没挂,本地一行 `bash scripts/ci_smoke.sh` 就能复刻。

### 4.2 Skills 评估 = 期末考试 + 分数线

想象你招了 3 个新员工(Skill):小出(出行)、小政(政策)、小像(画像)。他们上岗前得**先考试**——给他们 100 道题(用户消息),看他们能不能答对(选哪个 Skill)。

`tests/eval/skills_golden_set.jsonl` 就是**100+ 道题的题库**:

```jsonl
{"query": "帮我规划从北京到天津的低碳出行", "expected_skill": "low_carbon_travel", "category": "travel"}
{"query": "下雨天通勤建议怎么安排", "expected_skill": "low_carbon_travel", "category": "weather-travel"}
{"query": "switch to English please", "expected_skill": "low_carbon_travel", "category": "language-switch"}
```

`scripts/eval_skills.py` 是**阅卷老师**:

- 用 `select_skill()` 启发式(`TRAVEL_STRONG_ZH` / `POLICY_STRONG_EN` 等强信号字典)给每个 Skill 打分
- 取最高分的当答案
- 跟 `expected_skill` 对,**答对 +1,答错 +0**
- 总分 / 总题数 = trigger_accuracy

**分数线** = `THRESHOLD_TRIGGER = 0.90`(P11.B 新阈值,原 0.85)。< 0.90 就是**不及格**,CI 红灯,PR 卡掉。逼着开发者:**你加新 Skill 不能"凑合"**,得保证新 Skill 不把老 Skill 的题答错。

P11.B 把考试题从 20 扩到 100+(覆盖更多类目 + 中英双语),阈值也从 0.85 抬到 0.90 — **题难了、线高了**,Skill 质量自然水涨船高。

### 4.3 真实 MCP = 给机器人换"瑞士军刀"

之前机器人只自带 3 把瑞士军刀(mcp_mock_server 提供的 echo/weather/carbon),玩具级。真实 MCP 接入就像**给它换了一把真瑞士军刀**——能开瓶、能切菜、能拧螺丝、能改锥,什么都能干。

GitHub MCP server 暴露 30+ 工具,挑几个常见的:

- `mcp_github_create_issue` — 给仓库提 issue
- `mcp_github_list_repos` — 列你的仓库
- `mcp_github_get_file_contents` — 读文件
- `mcp_github_search_code` — 跨仓库搜代码

Notion MCP 类似(读 page / 搜 database / 写 block)。

**接入流程像买手机壳**:
1. **选壳**(在 yaml 加一条配置:GitHub / Notion / 自家 MCP)
2. **贴磁吸**(填 token 进 `.env`,yaml 用 `${GITHUB_TOKEN}` 占位)
3. **扣上去**(`enabled: true`,重启服务)
4. **验证**(查 `/api/mcp/status`)

**好处**:你不用懂 GitHub API 怎么调,只要在 chat 里说"给我的 repo 提个 issue 标题是 X",LLM 自己会去调 `mcp_github_create_issue`。

---

## 5. 10 步快速跑起来

```bash
# 1) 装依赖(httpx / pyyaml / pytest / ruff / docker 都要)
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 2) 看 CI 流水线长啥样(GitHub Actions YAML 解析一下)
cat .github/workflows/ci.yml | head -50
# 期望:看到 build-and-test + docker-build 两个 job

# 3) 本地一键 smoke(复刻 CI 的"docker 起 + 等 ready + 测 3 端点")
bash scripts/ci_smoke.sh
# 期望:看到 [ci-smoke] PASS /api/ready / PASS /api/health / PASS /api/chat

# 4) 跑 Skills 评估(100+ 题,触发准确率 ≥ 0.90 才算过)
python scripts/eval_skills.py
# 期望:看到 trigger_accuracy >= 0.90,exit 0
# 跑完会生成 data/skills_eval_report.md

# 5) 看 Skills 报告(按类目拆分 + 趋势)
cat data/skills_eval_report.md
# 期望:看到 travel / policy / profile / weather-travel 等类目各自的得分

# 6) 看 MCP 配置(P11.C 新增的 GitHub / Notion 模板)
cat config/mcp_servers.yaml | grep -A 8 "name: github"
# 期望:看到 enabled: false + transport: streamable-http + ${GITHUB_TOKEN}

# 7) 不接真实 MCP,只跑 mock(本地默认状态)
cd src && python main.py &
sleep 5
curl -s http://localhost:8000/api/mcp/status | python -m json.tool
# 期望:看到 mock_server connected,tools_count ~3

# 8) (可选)开 GitHub MCP — 填 .env 后改 yaml enabled
echo "GITHUB_TOKEN=ghp_your_token_here" >> .env
# 改 config/mcp_servers.yaml 里 github 那条 enabled: true
# 重启服务 → /api/mcp/status 应该看到 github connected,tools_count 30+

# 9) 全量回归(确认 P11 没破坏 P10 / P9 / P5-P6)
pytest tests/ -v -k "not paddle and not paddleocr" --tb=short
# 期望:100+ 通过(忽略 PaddleOCR / paddle 关键词的测试)

# 10) (可选)在本地模拟 CI 跑 ruff
ruff check src/ tests/
# 期望:看到 0 errors(可能有 warning,但 CI 配置里 || echo "lint warnings only" 不会卡)
```

**预期时间**:第 3 步首次跑因为要 build docker 镜像,约 3-5 分钟;后续每步秒级。第 4 步跑 100 条 trigger 评估约 5 秒。第 9 步全量回归约 1-2 分钟。

---

## 6. 怎么扩展(常见场景)

### 场景 A:加一个 CI 步骤(比如跑 mypy 类型检查)

1. 在 `.github/workflows/ci.yml` 的 `build-and-test` job 里,在 "Run ruff lint" 之后加:

```yaml
      - name: Run mypy type check
        run: |
          pip install mypy
          mypy src/ --ignore-missing-imports --no-strict-optional || echo "mypy warnings only"
```

2. 想本地复跑:`mypy src/ --ignore-missing-imports`
3. 想 CI 红灯而不是 warning:把 `|| echo "mypy warnings only"` 删掉,失败就直接 exit 1

**注意**:PaddleOCR / paddle 路径在 CI 里被 `-k "not paddle"` 排掉了,加步骤时也要小心,别引 OOM。

### 场景 B:给 Skills 评估加一个 trigger 测试

1. 打开 `tests/eval/skills_golden_set.jsonl`,追加一行(每行一个 JSON):

```jsonl
{"query": "垃圾分类怎么分", "expected_skill": "policy_query", "expected_behavior": ["policy_search"], "category": "policy"}
```

2. 跑 `python scripts/eval_skills.py`
3. 如果 trigger_accuracy 掉到 < 0.90,说明这个 query 启发式没识别出来,得调 `scripts/eval_skills.py` 里 `TRAVEL_STRONG_ZH` / `POLICY_STRONG_ZH` 等字典(加关键词)
4. 调完再跑,直到 ≥ 0.90,然后 `data/skills_eval_report.md` 会记录新分数

**注意**:`expected_skill` 必须是 `src/agent/skills/builtin.py` 里**实际注册**的 Skill 名,否则评估脚本会报 KeyError。

### 场景 C:接一个新的 MCP server(比如 Slack)

1. 在 `config/mcp_servers.yaml` 加一条:

```yaml
- name: slack
  description: Slack 官方 MCP(Streamable HTTP)
  enabled: true
  transport: streamable-http
  url: https://mcp.slack.com/mcp
  headers:
    Authorization: Bearer ${SLACK_TOKEN}
  origin: https://green-low-carbon-agent.local
  connect_timeout_s: 10.0
  request_timeout_s: 30.0
```

2. `.env` 加 `SLACK_TOKEN=xoxb_your_token`
3. 重启服务,自动连接
4. 验证:`curl http://localhost:8000/api/mcp/status` 应该看到 `slack` server 是 `connected` 状态
5. 在 chat 里试 "发一条消息到 #general 说下午 3 点开会" → LLM 会自动调 `mcp_slack_post_message`

**注意**:`origin` 字段是浏览器场景防 CSRF 用的,**必须填**,否则 server 会拒。`verify_ssl` 默认 true,本地测可以临时关。

---

## 7. 常见问题 FAQ

**Q1:CI 在本地跑没问题,GitHub Actions 上挂了,为啥?**

A:常见原因有三个:**(1)** Linux 路径分隔符(`/` vs `\\`),Windows 上 `os.path.join` 跑得好,Linux 上漏 `/` 就 404;**(2)** 环境变量大小写敏感(`.env` 里 `Github_Token` 跟 yaml 里 `${GITHUB_TOKEN}` 对不上);**(3)** ChromaDB / PaddleOCR 在 CI runner 上 OOM(磁盘 / 内存不够),已经被 `-k "not paddle"` 排除。修法:**先看 GitHub Actions 日志**(点进 job → 看 step 输出),定位到具体哪个 test 挂了再修。

**Q2:`bash scripts/ci_smoke.sh` 一直卡在 "Waiting for service to be ready"**

A:容器起不来或 `/api/ready` 没在 60s 内返 200。先 `docker ps -a | grep green-agent` 看容器在不在;在的话 `docker logs green-agent | tail -50` 看启动日志;不在的话 `docker build . -t green-agent:test` 看 build 有没有报错。常见原因:**端口 8000 被占**(`HOST_PORT=8001 bash scripts/ci_smoke.sh` 换个端口)、**镜像没 build**(`docker images | grep green-agent`)。

**Q3:`trigger_accuracy` 评估在哪跑?CI 怎么接入?**

A:本地 `python scripts/eval_skills.py`,默认阈值 0.90。CI 接入:在 `.github/workflows/ci.yml` 加一个 step:

```yaml
      - name: Skills trigger eval
        run: python scripts/eval_skills.py
        # exit 0 = 通过,exit 1 = 不达标,CI 红灯
```

建议放在 `Run ruff lint` 之前或之后都行,反正谁先挂谁先红。跟 `scripts/eval_retrieval.py` 同款套路。

**Q4:`${GITHUB_TOKEN}` 没被展开,server log 显示原样**

A:环境变量没设或加载顺序问题。**修法**:**(1)** 确认 `.env` 里 `GITHUB_TOKEN=` 后面没空格、没引号包裹;**(2)** 启动前 `set -a; source .env; set +a`(让 env 真正注入到子进程);**(3)** 重启服务(env 在 `fork` 时才继承)。`MCPRegistry._expand_env()` 没找到变量时**保留 `${VAR}`** 让你知道缺哪个,**不会静默 fail**。

**Q5:Skill 名字改了,golden set 没更新,会怎样?**

A:`scripts/eval_skills.py` 会 KeyError 退出(找不到 `expected_skill` 对应的类)。**修法**:**Skill 改名 = 改 builtin.py + 改 golden set + 改 SKILL.md 三件套**。或者用 `replace_all: true` 一次性替换 `tests/eval/skills_golden_set.jsonl` 里所有旧名字。**强烈建议改名时一次性三处都改**,免得 CI 反复红灯。

---

## 8. 推荐阅读顺序(给实习生)

如果你完全没接触过本项目的 CI / 评估 / MCP,按这个顺序看:

1. **`README.md`**(项目根)—— 5 分钟,了解项目目标和 quickstart
2. **`CLAUDE.md`**(项目根)—— 30 分钟,看完整架构图 + 模块说明
3. **`docs/learning/p9-ocr.md`** + **`docs/learning/p10-skills-mcp.md`** —— 60 分钟,看 P9 / P10 的"前一代"文档
4. **本文档**(`docs/learning/p11-productionization.md`)—— 30 分钟,聚焦 P11
5. **姊妹篇**(`docs/learning/p11-real-mcp.md`)—— 15 分钟,看真实 MCP 怎么开(用户视角)
6. **`.github/workflows/ci.yml`** —— 20 分钟,从上往下读两个 job,看每个 step 在干啥
7. **`scripts/ci_smoke.sh`** —— 15 分钟,看本地怎么一行复刻 CI 的"起容器 + smoke"
8. **`scripts/eval_skills.py`** —— 20 分钟,看 `select_skill()` 启发式打分逻辑 + 阈值常量
9. **`tests/eval/skills_golden_set.jsonl`** —— 10 分钟,看 100+ 道题长啥样,加新测试就照这个格式
10. **`config/mcp_servers.yaml`** —— 10 分钟,看 `enabled: false` 默认 + `${GITHUB_TOKEN}` 占位怎么写
11. **`src/mcp/registry.py`** —— 20 分钟,看 `_expand_env()`(P11.C 新增)+ `_instantiate_client()` 分发
12. **`data/skills_eval_report.md`** —— 5 分钟,看评估报告长啥样(跑过 eval 后才有)

**跑起来之前**:确保本机有 **Docker**(跑 ci_smoke.sh 用)+ **Python 3.10+**(项目要求)+ **pytest / ruff / httpx / pyyaml**(全在 `requirements-dev.txt`)。

**上手第一个 PR 建议**:在 `tests/eval/skills_golden_set.jsonl` 末尾追加 1 行 trigger 测试(比如 `"新能源汽车补贴 2026 还有吗"` → `policy_query`),然后 `python scripts/eval_skills.py` 验证 trigger_accuracy 仍 ≥ 0.90。这个改动一行、好 review、能帮你吃透评估闭环。

---

## 附录:快速对照表

| 想做的事 | 改哪个文件 / 跑哪个命令 |
|---|---|
| 看 CI 流水线 | `.github/workflows/ci.yml` |
| 本地复刻 CI | `bash scripts/ci_smoke.sh` |
| 跑 Skills 评估 | `python scripts/eval_skills.py` |
| 调 Skills CI 阈值 | `scripts/eval_skills.py` 的 `THRESHOLD_TRIGGER`(默认 0.90) |
| 加 trigger 测试 | `tests/eval/skills_golden_set.jsonl` 追加一行 |
| 看 Skills 评估报告 | `data/skills_eval_report.md`(跑 eval 后生成) |
| 看 MCP 连接状态 | `curl http://localhost:8000/api/mcp/status` |
| 开真实 MCP(GitHub) | `.env` 填 `GITHUB_TOKEN` + yaml 里 `github.enabled: true` |
| 开真实 MCP(Notion) | `.env` 填 `NOTION_TOKEN` + yaml 里 `notion.enabled: true` + oauth_token |
| 接新 MCP server(Slack) | `config/mcp_servers.yaml` 加一条 + `.env` 加对应 token |
| 加 CI 步骤 | `.github/workflows/ci.yml` 的 `build-and-test` job 加 step |
| 加 MCP transport | `src/mcp/<transport>_client.py` + `MCPRegistry._instantiate_client()` 分发 |
| 调 Skills 触发关键词权重 | `scripts/eval_skills.py` 的 `select_skill()` 启发式打分 |
| 调 LLM mock 模式 | `export LLM_MOCK=true` + `export USE_MOCK_LLM=true`(CI 默认开) |
| 改 ruff 规则 | `pyproject.toml` 的 `[tool.ruff]` 段 |

---

*版本:v1.0 | 创建于 P11.A/B/C 完成时 | 维护者:文档工程师*
