# Jev 需求路由接入

本次修改直接位于 D:/green-agent。Jev 仅做需求分类，不替代方案生成 LLM、
高德工具、节能计算、画像写入权限或证据校验。Obsidian 与数据库格式不变。

## 当前验收状态（2026-09-29）

官方 skill 已下载到 `skills/typesafe-ai/SKILL.md`，MIT 许可证保留。
这是开发指导文档，不是自动执行的程序。`plugins/jev_skill.py` 提供运行时适配：
- 注册全局 `jev_route` 工具和 `jev-decision` 技能，ReAct 工具提示词可见。
- `operation=guide` 返回官方原文及本项目边界；`operation=route` 执行有限需求分类。
- 原聊天需求路由与该工具共用 `agent.routing.jev.propose` 及服务端 OpenRouter 密钥。
- 本轮只实现 Choice 需求判断；官方文档中的通用 Score、Noul、重排序不是已完成功能。
- `GET /api/jev/status` 要求登录，仅返回配置与 skill 哈希，不返回密钥、不额外计费；
  其 network_verified=false 表示该状态接口没有主动探测网络，不是历史验收失败。

根目录 .env 的非秘密配置已设为 OpenRouter / typesafe/jev-1.13 / active / hybrid，
LLM_MOCK=false，超时 6 秒。已有 OPENROUTER_API_KEY 保持原值，未写入前端或文档。
这里“全局”指绿色低碳智能体后端，不是电脑的系统环境或 Codex 全局技能。
不同登录用户的分类请求使用同一个服务端计费密钥；现有聊天生成模型的用户密钥策略不变。

专项：122 passed、3 skipped（默认联网测试关闭）。随后单独执行真实验收：
`python scripts/check_jev.py --live`，3/3 通过。
虚构中文样例：家庭节能 1261ms / 出行 773ms / 多轮节能续接 910ms，均 source=jev。
初始 3 秒测试曾有一次出行超时；当前配置 6 秒，保留失败回退，不保证每次响应成功。
脚本从根目录 .env 读取配置，默认只检查安装/配置，--live 才发起真实调用。
验收记录位于 `data/jev-verification-20260929/README.md`。

已启动本机 `http://localhost:8000`（监听 127.0.0.1），启动日志确认 jev_skill 加载无错。
不代表完整家庭节能生成、画像写回或地图导航已完成用户端到端验收。

## 配置

启动进程环境或项目根目录 .env 可设置以下变量（main.py 启动时加载 .env）。
用户于 2026-09-29 选择 OpenRouter，按下面配置：

```dotenv
JEV_PROVIDER=openrouter
OPENROUTER_API_KEY=<在本机填入自己的 OpenRouter 密钥，不要提交>
JEV_ROUTING_MODE=active
JEV_MODEL=typesafe/jev-1.13
JEV_MIN_CONFIDENCE=0.8
JEV_TIMEOUT_SECONDS=6
UNDERSTANDING_MODE=hybrid
LLM_MOCK=false
```

OpenRouter 调用 `https://openrouter.ai/api/alpha/decisions`，使用 state/questions
及 answers 响应契约，不调用 chat/completions。不要填写 `typesafe/jev-router`，
那是选择聊天模型的另一项产品。OpenRouter 模式只读取 OPENROUTER_API_KEY，
不读取或回退 TYPESAFE_API_KEY，无需给 TypeSafe 组织充值；调用仍取决于
OpenRouter 账号的可用额度与模型权限。切换平台时同步修改 JEV_MODEL，
若未设置则按平台使用上述默认模型。错误的平台/模型组合在发送前拒绝。

如需恢复 TypeSafe 直连，使用：

```dotenv
JEV_ROUTING_MODE=shadow
JEV_PROVIDER=typesafe
TYPESAFE_API_KEY=<在本机填入自己的 TypeSafe 密钥，不要提交>
JEV_MODEL=jev-1.13.0
JEV_MIN_CONFIDENCE=0.8
JEV_TIMEOUT_SECONDS=3
```

初次接入时没有修改 .env；2026-09-29 已按上述“当前验收状态”配置。代码默认模式 off 保持原行为，默认提供商
typesafe 兼容旧配置；选择 OpenRouter 必须设置 JEV_PROVIDER=openrouter。
- off：不调用 Jev。
- shadow：真实调用但不采用结果，仍由原 LLM/规则决定；会产生供应商费用。
- active：通过校验和门槛后采用 Jev，失败回退原 LLM/规则。

UNDERSTANDING_MODE=rules、LLM_MOCK=true 或显式注入测试模型时不调用 Jev。
UNDERSTANDING_MODE=shadow 不应用 Jev 结果。更新环境后需重启原 Web 进程。
Jev 密钥仅供分类使用，不能替代聊天所需的用户 LLM 密钥。

## 行为与边界

先保留取消、继续、任务切换、填槽、假设/否定等现有规则，再进入 Jev。
一次请求只选 energy_plan/travel_plan/energy_update/explain/report/clarify。
多轮关系由代码结合当前任务推导，Jev 不能返回任意工具名或画像字段。
energy_update 仍需当前家庭任务和已解析的家庭信息，不允许模型凭空写画像。
确认门槛同时约束所选项概率与供应商 confidence；0.8 是初始工程阈值，
尚未经本项目中文评测集校准，不能解释为 80% 的实际正确率。

出站内容仅当前消息、最多四条各 1000 字的历史、当前领域及待填槽名称，
经过项目现有 PII 脱敏；不发送完整画像、账号标识或 Obsidian。
脱敏不保证清除用户自由文本中所有个人信息。当前消息超过 6000 字直接回退。
固定官方 HTTPS 接口，TLS 校验开启，不跟随重定向，不重试；HTTP 各阶段超时
默认 3 秒（不是整条聊天链路的总时限），返回体限 64 KiB。
鉴权失败、限流、超时、非法类型/标签/概率、低置信度均回退。

日志 jev_route 记录提供商、结果原因、候选、置信度、耗时，不记录原文、密钥或响应正文。
采用结果时 Demand.source=jev，沿已有聊天 trace 显示来源。
本补丁还修复了 energy 领域覆盖 cancel/clarify 的错误；澄清与取消会正常返回。
这不等于已修复整个家庭节能执行过程的 SSE 展示。

## 验证

2026-09-29 初次 OpenRouter 接入专项：109 passed、3 skipped。HTTP MockTransport
覆盖两个平台、密钥隔离、错误模型名、401/402/429/5xx、超时和原路由回退。
当时未配置 OPENROUTER_API_KEY；后续真实调用和服务启动结果见本文顶部最新状态。

```powershell
python -m pytest tests/test_understanding.py -q -p no:cacheprovider --basetemp=D:/green-agent/data/pytest_jev
```

测试使用 HTTP MockTransport 验证请求契约、实际路由分支、概率校验、
服务失败回退、上下文范围、日志脱敏、取消和澄清。测试不写真实画像或 Obsidian。
更新旧测试替身以接受处理器新增关键字参数；原行为断言保留。

配置当前终端 OPENROUTER_API_KEY 后，运行显式联网验收（三个虚构中文场景）：

```powershell
$env:RUN_JEV_LIVE='1'
$env:JEV_LIVE_PROVIDER='openrouter'
python -m pytest tests/test_understanding.py -k jev_live_opt_in -q -p no:cacheprovider
Remove-Item Env:RUN_JEV_LIVE
Remove-Item Env:JEV_LIVE_PROVIDER
```

直连验收将 JEV_LIVE_PROVIDER 设为 typesafe，并配置 TYPESAFE_API_KEY。
联网验收使用所选提供商的默认固定模型和 0.8 门槛。
默认跳过联网测试；跳过不能算供应商验收通过。pytest 不自动加载 .env，
密钥需在测试进程环境中设置。没有密钥时不能宣称已调用真实 Jev或提升准确率。
正式启用前应固定版本，以同一批人工标注中文多轮输入比较原路由与 Jev 的
误判、无效追问、P50/P95 延迟和调用消耗；本轮尚未完成此对比。

2026-09-28 本地结果：以下命令 146 passed、3 skipped（真实供应商场景未启用）。
没有运行全库测试，没有重启运行中的 Web 服务，没有真实 Jev 调用证据。
原需求理解测试基线为 31 passed、3 failed：旧替身不接受新增处理器参数。

```powershell
python -m pytest tests/test_understanding.py tests/test_intent.py tests/test_energy_planner.py tests/test_energy_no_hallucination.py tests/test_travel_weather_safety.py tests/test_structured_profile_graph.py -q -p no:cacheprovider --basetemp=D:/green-agent/data/pytest_jev_regression
```

回退：设 JEV_ROUTING_MODE=off 后重启即可恢复原模型路由，无数据库迁移。

官方依据（2026-09-28 核对）：
- https://docs.typesafe.ai/api
- https://docs.typesafe.ai/models
- https://docs.typesafe.ai/introduction/quickstart
- https://openrouter.ai/blog/insights/what-is-jev/ （2026-09-29 核对 Decisions API）
