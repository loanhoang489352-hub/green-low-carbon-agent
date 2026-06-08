# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

绿色低碳智能体是一个基于消费者偏好建模的个性化低碳生活助手,解决"知行鸿沟"(从知道绿色低碳到行动起来),通过三层记忆 + 用户画像图谱 + 个性化行动推荐,实现"个性化绿色低碳行为促进"。

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动 Web 服务(默认端口 8000)
cd src && python main.py

# 命令行模式
cd src && python main.py --cli

# 使用 LangGraph 工作流(实验性)
cd src && python main.py --use-langgraph --use-react

# 运行测试
pytest tests/ -v

# 单个测试
pytest tests/test_p3_integration.py::test_event_bus_basic -v
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
│   ├── memory/                # 三层记忆
│   │   ├── short_term.py      # 短期(单例 + 双检锁,带 TTL 清理)
│   │   ├── long_term.py       # 长期(SQLite + WAL,带热度/衰减)
│   │   └── consolidation.py   # 整合机制(策略模式:P4-余 后)
│   ├── knowledge/             # 知识库管理 + 增量更新器
│   ├── rag/                   # RAG 引擎(混合:语义+BM25)+ GraphRAG
│   │   ├── rag_engine.py      # RAGEngine(singleton 计划 P4-E)
│   │   ├── graphrag.py        # GraphRAG 引擎(实体/关系提取 + 多跳推理)
│   │   └── rag_subscriber.py  # 订阅 KNOWLEDGE_UPDATED 重建索引
│   ├── user_profile/          # 画像 + 行为追踪 + 推荐
│   │   ├── user_profile.py    # UserProfileManager
│   │   ├── profile_graph.py   # UserProfileGraph(P4-C 接入)
│   │   ├── behavior_tracker.py
│   │   ├── goal_tracker.py
│   │   ├── achievement_system.py
│   │   ├── carbon_footprint.py
│   │   └── personalized_recommender.py
│   ├── policy/                # 政策更新(P4-E 实爬 httpx+BS4)
│   ├── tools/                 # 工具抽象(BaseTool, ToolRegistry, ToolExecutor)
│   ├── planner/               # 任务规划(TaskDecomposer, Planner/ReActPlanner)
│   └── graph/                 # LangGraph 工作流
│       ├── state.py           # AgentState 状态定义
│       ├── nodes.py           # 6 节点(intent/retrieve/recommend/llm/format/reflection)
│       └── graph.py           # 工作流图(P4-A 计划挂 SqliteSaver checkpointer)
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
- P3-余 后通过 `get_consolidator()` 接入记忆整合(P4-B 完善)
- `ConversationContext` 取代原 `session_manager.py`,在 P4-B 抽出独立 `ConversationStore`

**`src/agent/langgraph_agent.py` - LangGraphAgent**
- 基于 LangGraph StateGraph 的替代实现
- 6 节点定义在 `agent/graph/nodes.py`(P4-B 接入短期记忆)
- 状态结构定义在 `agent/graph/state.py`
- 支持 ReAct 模式(含反思节点)
- P4-A 计划挂 SqliteSaver checkpointer

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

**`src/memory/consolidation.py` - 记忆整合(P4-余 后改为策略模式)**
- 触发条件:对话轮次≥10 / 空闲≥2h / 消息数≥20
- 重要性阈值:0.6
- 整合到 `long_term.user_memories` 表

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

**`src/user_profile/profile_graph.py` - 用户画像图谱(P4-C 接入)**
- 节点类型:User, Interest, Action, Goal, Achievement, CarbonFootprint
- 边关系:has_interest, performs_action, has_goal, earned_achievement, reduces_carbon
- 序列化为 `profile_data["graph"]` JSON 子字段(零新依赖)
- 当前**尚未接入 UserProfileManager**(P4-C 计划完成)

### 三层记忆 + 画像图谱 数据流(目标态,P4-B/C 完成后)

```
用户输入
  ├─→ [会话] ConversationContext(per-user,内存,带 TTL)
  ├─→ [短期] ShortTermMemory(单例,conversations dict,7 天 TTL)
  │     └─→ P4-B 后:LangGraph 6 节点统一调 add_message
  ├─→ [长期] LongTermMemory(SQLite + WAL)
  │     ├─→ MemoryConsolidator 触发后写入
  │     ├─→ search_memories(query) 召回相关(P4-B 改造)
  │     └─→ decay_importance 半衰期 30 天(P4-A 调度)
  ├─→ [画像] UserProfileManager.get_profile(user_id)
  │     └─→ UserProfileGraph(P4-C):节点/边 JSON 化
  ├─→ [RAG] RAGEngine.query(query, filter_metadata=用户地区/兴趣)
  │     └─→ KNOWLEDGE_UPDATED 事件触发 rebuild_index(P4-E)
  └─→ LLM 调用(prompt 注入:画像/记忆/RAG/阶段策略)
```

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
  - `policy/national/`, `policy/{region}/` (P4-F 计划按地区切分)
- `data/vector_db/`: ChromaDB 向量数据库
- `data/accounts.db`: 账号与会话
- `data/user_profiles.db`: 画像(JSON)+ goals + achievements + carbon_footprint(P4-C)
- `data/feedback.db`: 消息反馈
- `data/policy_updates.db`: 政策库 + update_logs
- `data/long_term_memory.db`: 长期记忆 + user_preferences
- `data/behavior_tracker.db`: 行为事件
- `data/langgraph_checkpoints.db`: LangGraph 状态快照(P4-A 计划)

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

## 重构进度(P0–P3 7 个 commit)

| Commit | 阶段 | 摘要 |
|---|---|---|
| `0b06688` | P0 | 4 个真实 API 密钥轮换 + git-filter-repo 清理历史 + 5 个致命 Bug |
| `cd32f86` | P1 | ThreadingHTTPServer + DB WAL + 工具超时 + ReAct step_count |
| `ac722eb` | P2 | `paths.py` + `config.py` + `response_mapper.py` + 死代码清理 |
| `57808a4` | P2-余 | `config/cities.yaml` + `config/sources.yaml` 外部化 |
| `2d38ad0` | P2-余 | main.py 拆为 `src/server/{routers,app}.py` 13 路由 |
| `a668c28` | P1-余 | planner 失败任务显式化 + GraphRAG O(N²)→O(N) |
| `37966cc` | P3 | 事件总线 + 知识库更新事件 + 反馈→画像回流 + Schema Registry |

**当前计划(2026-06)**: P3-余(文档/依赖/抽象)+ P4-A~G(核心愿景实现),详见 `docs/refactor-plan-v2.md` 与 `~/.claude/plans/bug-agent-groovy-flute.md`。
