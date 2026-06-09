# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

绿色低碳智能体是一个基于消费者偏好建模的个性化低碳生活助手,解决"知行鸿沟"(从知道绿色低碳到行动起来),通过**三层记忆(短+工作+长,P4-H)+ 用户画像图谱 + 实时知识同步 + 个性化行动推荐**,实现"个性化绿色低碳行为促进"。P0–P4-G + P4-H 已完成(共 14 个 commit),端到端可运行。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Web 服务(默认端口 8000)
cd src && python main.py

# 命令行模式
cd src && python main.py --cli

# 使用 LangGraph 工作流(实验性,ReAct 模式)
cd src && python main.py --use-langgraph --use-react

# 运行测试
pytest tests/ -v

# 单个测试
pytest tests/test_p4g_e2e.py::test_chat_enhanced_knowledge_query -v
```

## 架构概览

```
src/
├── main.py                    # 入口(实际委托给 server.app)
├── paths.py                   # 统一路径管理(PROJECT_ROOT, DATA_DIR, 各 DB 路径)
├── config.py                  # Pydantic Settings(LLMConfig, ExecutionConfig, ServerConfig, RAGConfig)
├── config_loader.py           # YAML 配置加载(cities.yaml, sources.yaml,带 lru_cache)
├── db_schema.py               # Schema Registry:6 个 SQLite DB 集中管理(替代 Alembic)
├── events.py                  # 事件总线(EventBus + EventType)
├── server/                    # HTTP 服务(P2-余 拆分产物)
│   ├── app.py                 # RoutedRequestHandler + init_app() + create_handler
│   ├── router.py              # Route dataclass + RouterRegistry
│   ├── errors.py              # 统一 JSON 错误响应
│   └── routers/               # 13 路由,按资源拆 8 个文件
│       ├── system.py          # /api/health, /api/chat, /api/chat/enhanced
│       ├── auth.py            # /api/auth/{login,register,logout}
│       ├── profile.py         # /api/profile
│       ├── onboarding.py      # /api/onboarding/{start,answer,status}
│       ├── feedback.py        # /api/feedback
│       ├── knowledge.py       # /api/knowledge/{stats,query,reload}
│       ├── policy.py          # /api/policy/{latest,summary,sync}
│       └── memory.py          # /api/memory/{short,long}
├── agent/
│   ├── core.py                # GreenAgent 核心编排器(chat/chat_enhanced)
│   ├── langgraph_agent.py     # LangGraphAgent(StateGraph 替代实现)
│   ├── response.py            # 响应生成
│   ├── response_mapper.py     # IntentType → response_type 单一映射源
│   ├── intent.py              # 意图识别(规则+关键词)
│   ├── memory/                # 三层记忆(短+工作+长,P4-H)
│   │   ├── short_term.py      # 短期(单例 + 双检锁,带 TTL 清理)
│   │   ├── working.py         # 工作记忆(P4-H:per-user workspace + 同名覆盖检测)
│   │   ├── memory_agent.py    # P4-H:级联召回(短→工作→长,先用免费的)
│   │   ├── long_term.py       # 长期(SQLite + WAL,带热度/衰减)
│   │   └── consolidation.py   # 整合机制(策略模式, P4-H 加入 短→工作 晋升)
│   ├── knowledge/             # 知识库管理 + 增量更新器
│   ├── rag/                   # RAG 引擎(混合:语义+BM25)+ GraphRAG
│   │   ├── rag_engine.py      # RAGEngine(P4-E 加 get_rag_engine 单例)
│   │   ├── vector_store.py    # ChromaDB/FAISS/内存,P4-G 修正 score 公式
│   │   ├── graphrag.py        # GraphRAG 引擎(实体/关系提取 + 多跳推理)
│   │   └── rag_subscriber.py  # 订阅 KNOWLEDGE_UPDATED 重建索引
│   ├── user_profile/          # 画像 + 行为追踪 + 推荐
│   │   ├── user_profile.py    # UserProfileManager
│   │   ├── profile_graph.py   # UserProfileGraph(P4-C 接入,P4-G 加去重)
│   │   ├── persistence.py     # 行为事件/目标/成就/碳足迹持久化层(P4-C)
│   │   ├── behavior_tracker.py
│   │   ├── goal_tracker.py
│   │   ├── achievement_system.py
│   │   ├── carbon_footprint.py
│   │   ├── dynamic_updater.py # analyze_message → detected_interests/action_reports
│   │   └── personalized_recommender.py  # 含 augment_with_rag(P4-F.3)
│   ├── policy/                # 政策更新(P4-E 实爬 httpx+BS4)
│   ├── tools/                 # 工具抽象(BaseTool, ToolRegistry, ToolExecutor)
│   ├── planner/               # 任务规划(TaskDecomposer, Planner/ReActPlanner)
│   ├── scheduler.py           # APScheduler 后台调度(P4-A:每日 kb 更新/记忆衰减)
│   ├── conversation_store.py  # 会话单例(P4-B.5)
│   └── graph/                 # LangGraph 工作流
│       ├── state.py           # AgentState 状态定义
│       ├── nodes.py           # 6 节点 + 软过滤 + 画像回写(P4-F/P4-G)
│       └── graph.py           # 工作流图(P4-A 挂 SqliteSaver + P4-G 补 ReAct 前置节点)
├── feedback/                  # 反馈管理
│   ├── feedback_manager.py    # FeedbackManager(publish FEEDBACK_RECEIVED)
│   └── profile_subscriber.py # 订阅反馈事件回流画像
└── auth/                      # 账户管理(账号 + 会话)
    └── account_manager.py
```

### 关键模块说明

**`src/agent/core.py` - GreenAgent**
- 核心编排器,延迟加载各模块
- 提供 `chat()` 和 `chat_enhanced()` 两个接口
- 当 `USE_LANGGRAPH=true` 时委托给 LangGraph 工作流
- **P4-B**:通过 `get_consolidator()` 接入记忆整合 + `_recall_memories()` 真正语义召回
- **P4-B.5**:`ConversationContext` 抽出为独立 `src/agent/conversation_store.py` 单例,`active_conversations` / `user_conversations` 改为引用 store 内部 dict

**`src/agent/langgraph_agent.py` - LangGraphAgent**
- 基于 LangGraph StateGraph 的替代实现
- 6 节点定义在 `agent/graph/nodes.py`
- 状态结构定义在 `agent/graph/state.py`
- 支持 ReAct 模式(含反思节点)
- **P4-A**:挂 SqliteSaver checkpointer(`data/langgraph_checkpoints.db`,WAL 模式)
- **P4-B.5**:与 GreenAgent 共享 `ConversationStore` 单例
- **P4-B.1/B.2**:`generate_response` 节点末尾触发 consolidator

**`src/agent/conversation_store.py` - 会话存储单例(P4-B.5)**
- 双检锁单例,跨 GreenAgent / LangGraphAgent 共享
- 持有 `user_id → conversation_id` 列表与 `conversation_id → ConversationContext` 映射
- TTL 7 天,可由 scheduler 周期 `cleanup_expired()`

**`src/server/` - HTTP 服务**
- `app.py` 的 `init_app()` 完成订阅注册、调度器启动、各 router 注册
- `router.py` 的 `RouterRegistry` 管理 `Route(method, path, handler)` 列表
- 每个 router 文件用 `register(router_registry)` 把 handler 注入

**`src/events.py` - 事件总线**
- `EventBus` 单例 + `subscribe/publish/unsubscribe`
- 订阅者异常隔离(不阻塞其他订阅者)
- `EventType` 枚举:`KNOWLEDGE_UPDATED` / `FEEDBACK_RECEIVED` / ...

**`src/db_schema.py` - Schema Registry**
- 6 个 SQLite DB 集中管理(accounts, user_profiles, feedback, policy_updates, long_term_memory, behavior_tracker)
- `init_all_schemas()` 幂等初始化(WAL 模式)
- 后续切换到 Alembic 时,`SCHEMAS` 即初始 migration 起点

**`src/agent/tools/` - 工具抽象层**
- `BaseTool`:工具抽象基类,所有工具必须实现 name, description, parameters, execute()
- `ToolRegistry`:工具注册中心,支持注册、发现、参数校验
- `ToolExecutor`:工具执行器,支持超时控制(用 `ThreadPoolExecutor.submit().result(timeout=...)`)、错误处理、重试

**`src/agent/planner/` - 任务规划模块**
- `Task`:原子任务单元(task_id, task_type, dependencies, status, result, error)
- `TaskDecomposer`:任务分解器,支持简单/复合/复杂三种模式
- `Planner` / `ReActPlanner`:任务规划器,**失败任务显式记入 `failed_tasks`**(P1-余 修复)

**`src/memory/consolidation.py` - 记忆整合(策略模式)**
- `ConsolidationStrategy` Protocol,`ThresholdStrategy` / `AdaptiveStrategy` 实现
- 触发条件:对话轮次≥10 / 空闲≥2h / 消息数≥20
- 重要性阈值:0.6
- `get_consolidator("adaptive")` 工厂,**P4-B** 接入到 `chat()` / `chat_enhanced()` / LangGraph `generate_response` 节点
- 整合到 `long_term.user_memories` 表

**`src/memory/long_term.py` - 长期记忆(P4-B.3)**
- `user_memories` 表的 `last_accessed` / `access_count` 在 `get_recent_memories` / `search_memories` 时自动更新
- `decay_importance(half_life_days=30)` 按半衰期公式 `rate = 0.5 ** (days / half_life)` 衰减
- 兼容旧 `decay_importance(decay_rate=0.95)` 调用

**`src/rag/graphrag.py` - GraphRAG 引擎**
- 基于知识图谱的检索增强,支持多跳推理问答
- `EntityExtractor`:实体提取(concept/action/policy/metric/location)
- `RelationExtractor`:关系提取(affects/causes/contains 等)
- P1-余 后关系去重 O(N²) → O(N)
- P4-E 计划:加 `get_instance()` 单例,订阅 `KNOWLEDGE_UPDATED` 自动重建

**`src/knowledge/updater.py` - 知识库增量更新器**
- `KnowledgeUpdater`:检查外部政策源变化
- 支持多源配置(`config/sources.yaml`)
- 增量更新,**完成后 publish `KNOWLEDGE_UPDATED`**(P3 已加)
- P4-E 计划:加 `content_hash` 去重 + 版本管理

**`src/user_profile/profile_graph.py` - 用户画像图谱(P4-C 接入,P4-G 加去重)**
- 节点类型:User, Interest, Action, Goal, Achievement, CarbonFootprint
- 边关系:has_interest, performs_action, has_goal, earned_achievement, reduces_carbon
- 序列化为 `profile_data["graph"]` JSON 子字段(零新依赖)
- **P4-C.2**:UserProfileManager `update_eco_profile` 同步到图谱(interest / stage / action_history)
- **P4-G**:`add_interest` / `add_action` 边/节点去重(同 user-兴趣对只保留一条,取最高置信度)
- 反序列化 `from_dict(data)`,零状态丢失

**`src/user_profile/persistence.py` - 行为/目标/成就/碳足迹持久化层(P4-C)**
- 4 张表(behavior_events / user_goals / user_achievements / carbon_footprint_log)落在 `behavior_tracker.db`
- `BehaviorPersistence.record_event` / `create_goal`(自动完成)/ `grant_achievement`(UNIQUE 去重)/ `record_carbon` / `calculate_weekly_total`
- 单例 `_persistence`,模块级 get_behavior_persistence() 工厂

**`src/agent/conversation_store.py` - 会话存储单例(P4-B.5)**
- 双检锁单例,跨 GreenAgent / LangGraphAgent 共享
- 持有 `user_id → conversation_id` 列表与 `conversation_id → ConversationContext` 映射
- TTL 7 天,可由 scheduler 周期 `cleanup_expired()`

**`src/scheduler.py` - APScheduler 后台调度(P4-A)**
- `start_scheduler()` 启动 BackgroundScheduler(daemon=True)
- 每日 02:00 全量增量知识/政策更新(daily_kb)
- 每日 03:00 长期记忆半衰期衰减(memory_decay,半衰期 30 天)
- 启动时 `init_app()` 调用,关闭时 `sched.shutdown(wait=False)`

**`src/policy/updater.py` - 政策实爬(P4-E)**
- `PolicyUpdater._fetch_url` 用 httpx(30s timeout, 自定义 User-Agent)
- `_extract_content` 优先 BS4 CSS 选择器,退化到 trafilatura 通用提取
- `_fetch_and_ingest` 抓取→提取→`add_policy`→发布 `KNOWLEDGE_UPDATED` 事件
- `add_policy` UPSERT 去重(source_url + content_hash 唯一)

**`src/rag/rag_engine.py` - RAG 引擎 + 单例(P4-E)**
- `get_rag_engine(config=None)` 双检锁单例(供 RAG 订阅者直接调 rebuild_index)
- `reset_rag_engine()` 测试用
- `RAGConfig.min_similarity=0.0`(P4-G:MiniLM 距离大,0.3 会漏检)

**`src/rag/vector_store.py` - 向量存储(P4-G 修复)**
- ChromaDB 路径:`score = 1.0/(1.0+distance)`(兼容非归一化向量)
- FAISS 路径:同样的倒数归一化
- Inmemory 路径:余弦相似度(已正确)

**`src/agent/graph/nodes.py` - LangGraph 节点 + 软过滤 + 画像回写(P4-F/P4-G)**
- `_build_personalization_hints` 从画像提 region + interests
- `_rerank_by_personalization` 软重排(region *1.3 / interest *1.15)
- `_region_aliases` 北京→beijing 等中英文互转
- `_interest_keywords` low_carbon_travel→travel/出行 等关键词映射
- `_apply_profile_updates` 把 detected_interests + behavior_stage + action_reports 写回画像图谱
- 修: `_rag_engine.query()` → `retrieve()`; `analyze_message` 签名变化; `generate_recommendations` 关键字参

### 三层记忆 + 画像图谱 数据流(P4-B/C/F/G + P4-H 完成态)

```
用户输入
  ├─→ [会话] ConversationStore(单例,user_id → conversation_id,7 天 TTL)
  ├─→ [短期] ShortTermMemory(单例,conversations dict,7 天 TTL)
  │     └─→ P4-B 后:LangGraph 节点统一调 add_message(recognize_intent / generate_response)
  ├─→ [工作] WorkingMemory(P4-H:per-user workspace, JSON 快照跨会话)
  │     ├─→ 命名空间 set/get/delete,同名 key 覆盖检测(防任务污染)
  │     ├─→ end_task(clear=True) 防污染 / clear=False 跨任务共享
  │     └─→ snapshot_for_prompt 注入 LLM 系统 prompt
  ├─→ [长期] LongTermMemory(SQLite + WAL)
  │     ├─→ P4-H:MemoryConsolidator 短→工作→长 三段晋升
  │     ├─→ search_memories(query) 召回相关,带热度更新(P4-B.3)
  │     ├─→ decay_importance 半衰期 30 天(P4-A 调度)
  │     └─→ P4-H:working_memory_heartbeat 每 4h 清理过期+晋升高 importance
  ├─→ [级联召回] cascaded_recall(P4-H)
  │     ├─→ should_recall 扫信号词("上次/之前/那个")
  │     └─→ 短→工作→长 级联,能用免费的就用免费的
  ├─→ [画像] UserProfileManager.get_profile(user_id)
  │     └─→ UserProfileGraph(P4-C):节点/边 JSON 化,加去重
  │     └─→ update_profile 节点回写 detected_interests/stage/actions → 图谱
  ├─→ [RAG] RAGEngine.retrieve(query, top_k=8) + 软重排
  │     └─→ retrieve_knowledge 节点用 region/interests 加权
  │     └─→ augment_with_rag 把 RAG 结果插入推荐头部
  └─→ LLM 调用(prompt 注入:画像/工作记忆/长期记忆/RAG/阶段策略)
```

### 三层记忆对照表(P4-H)

| 维度 | 短期 | 工作(P4-H 新增) | 长期 |
|---|---|---|---|
| 文件 | `short_term.py` | `working.py` | `long_term.py` |
| 粒度 | 对话消息 | 命名空间 key-value | 永久事实/偏好 |
| 范围 | 单 session | per-user 跨 session | 全局 |
| 容量 | 5 轮 + 摘要 | 上限 50 key,LRU 淘汰 | 索引 < 40 行 |
| 淘汰 | 旧轮次→摘要 | end_task 清空 / 24h TTL / 50-key LRU | 半衰期 30 天衰减 |
| 持久化 | 内存(`conversations` dict) | 内存 + JSON 快照 | SQLite + WAL |
| 召回 | `get_conversation_history` | `cascaded_recall(working=...)` | `search_memories` |
| 注入 prompt | `conversation_history` 字段 | `working_memory` system msg | `recent_memories` / 长召回 |
| 写入 | 节点出口 add_message | 自由 set / heartbeat 审计 | 整合后 consolidate |
| 风格 | — | OpenClaw(自由+定期审计) | — |
| 测试 | `test_p4b_memory.py` | `test_p4h_working_memory.py`(15 个) | `test_p4b_memory.py` |

### 用户引导流程(Onboarding)

`/api/onboarding/start` → `/api/onboarding/answer` 逐步问卷,共 8 步:年龄段、性别、地区、收入水平、家庭规模、环保关注领域、环保知识水平、行为阶段。

### 意图类型(IntentType)

`KNOWLEDGE_QUERY`, `ADVICE_REQUEST`, `ACTION_REPORT`, `FEEDBACK`, `GREETING`, `OTHER`

## 配置

- `config/settings.yaml`: LLM 提供商、向量数据库、知识库路径等
- `config/cities.yaml`: 城市配置(默认北京,识别 10 个主要城市)— P2-余 外部化
- `config/sources.yaml`: 政策源 URL — P2-余 外部化
- `.env`: API 密钥(`__SET_ME__` 占位符)
- `USE_LANGGRAPH=true`: 启用 LangGraph 工作流(P2 合并为 `execution_mode` 枚举)
- `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`: CORS 白名单

## 数据目录

- `knowledge_base/`: Markdown 格式知识文档(basic/policy/guide 三类)
  - `policy/national_policy.md` 全国级
  - `policy/beijing_low_carbon.md` 等(P4-F 加的地区级)
- `data/vector_db/`: ChromaDB 向量数据库
- `data/accounts.db`: 账号与会话
- `data/user_profiles.db`: 画像(JSON + graph 子字段,P4-C)
- `data/feedback.db`: 消息反馈
- `data/policy_updates.db`: 政策库 + update_logs
- `data/long_term_memory.db`: 长期记忆 + user_preferences
- `data/behavior_tracker.db`: 行为事件 + goals + achievements + carbon(P4-C)
- `data/langgraph_checkpoints.db`: LangGraph 状态快照(P4-A)

## API 端点(13 路由)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/chat` | POST | 基础聊天 |
| `/api/chat/enhanced` | POST | 增强聊天(RAG+个性化) |
| `/api/auth/register` | POST | 用户注册 |
| `/api/auth/login` | POST | 登录 |
| `/api/auth/logout` | POST | 登出 |
| `/api/profile` | GET/PUT | 获取/更新画像 |
| `/api/onboarding/start` | POST | 开始引导 |
| `/api/onboarding/answer` | POST | 回答引导问题 |
| `/api/feedback` | POST | 提交反馈(点赞/点踩/评论) |
| `/api/knowledge/stats` | GET | 知识库统计 |
| `/api/knowledge/query` | POST | 知识库查询 |
| `/api/knowledge/reload` | POST | 强制 RAG 重建 |
| `/api/policy/latest` | GET | 最新政策 |
| `/api/policy/summary` | GET | 政策摘要 |
| `/api/policy/sync` | POST | 触发政策爬取(P4-E 后) |
| `/api/memory/short` | GET | 短期记忆 |
| `/api/memory/long` | GET | 长期记忆 |
| `/` | GET | Web 界面 |

## 重构进度(P0–P4 共 13 个 commit,所有 P4 已完成)

| Commit | 阶段 | 摘要 |
|---|---|---|
| `0b06688` | P0 | 4 个真实 API 密钥轮换 + git-filter-repo 清理历史 + 5 个致命 Bug |
| `cd32f86` | P1 | ThreadingHTTPServer + DB WAL + 工具超时 + ReAct step_count |
| `ac722eb` | P2 | `paths.py` + `config.py` + `response_mapper.py` + 死代码清理 |
| `57808a4` | P2-余 | `config/cities.yaml` + `config/sources.yaml` 外部化 |
| `2d38ad0` | P2-余 | main.py 拆为 `src/server/{routers,app}.py` 13 路由 |
| `a668c28` | P1-余 | planner 失败任务显式化 + GraphRAG O(N²)→O(N) |
| `37966cc` | P3 | 事件总线 + 知识库更新事件 + 反馈→画像回流 + Schema Registry |
| `fcfd6a1` | P3-余 | 文档同步 + 依赖瘦身 + Consolidation 策略模式 |
| `bba7c75` | P4-A | 启动时事件订阅 + APScheduler + LangGraph SqliteSaver checkpointer |
| `a110b9d` | P4-B | 三层记忆真正打通(短→长 consolidation、热度、衰减、召回、会话单例) |
| `46f6db9` | P4-C | 用户画像图谱化 + 行为/目标/成就/碳足迹持久化 |
| `47479dc` | P4-D | 行为阶段真正驱动 LLM(5 阶段 prompt 差异化) |
| `dcc16ee` | P4-E | 实时知识/政策同步 + RAG 自动重载(httpx+bs4) |
| `b128d00` | P4-F | 知识库个性化(画像驱动 RAG 检索 + 静态推荐混合) |
| `dd7bdb5` | P4-G | 端到端修复 - agent 可正常运行,RAG 真正可用 |
| `P4-H` | P4-H | **三层记忆补齐** — 工作记忆(`working.py`)+ 级联召回(`memory_agent.py`)+ 短→工作→长 整合 + LLM prompt 注入 |

**P4 阶段成果**:
- 65 个 P4 单元/E2E 测试全过(`pytest tests/test_p4*.py -v`)
  - P4-A~G 共 50 + P4-H 新增 15(working memory 单例/覆盖检测/cross-session/级联召回/晋升 LTM/heartbeat)
- agent 端到端可运行:`chat_enhanced` 知识查询返回 4 个推荐(1 RAG + 3 静态)+ 3 个 knowledge_refs + 685 chars RAG context
- 多轮对话画像图谱正确更新(兴趣+行为,边/节点去重)
- 知识库按地区软过滤(北京用户→北京政策加分)
- 政策实爬 + RAG 订阅者自动重建索引
- **P4-H** 三层记忆(短+工作+长)真正打通:workspace 命名空间 + 同名 key 覆盖检测 + OpenClaw 风格 heartbeat(每 4h 清理过期 + 晋升高 importance)

**当前计划(2026-06)**: 详见 `~/.claude/plans/bug-agent-groovy-flute.md`(P0–P4-G 完成,P4-H 落地)。
