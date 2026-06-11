# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

绿色低碳智能体是一个基于消费者偏好建模的个性化低碳生活助手,解决"知行鸿沟"(从知道绿色低碳到行动起来),通过**三层记忆(短+工作+长,P4-H)+ 用户画像图谱 + 实时知识同步 + 个性化行动推荐**,实现"个性化绿色低碳行为促进"。P0–P4-H + P5-A→I 全部完成(共 23 commit),端到端可运行,达到 **production-ready 边界**;P5-J(部署/SRE)是 plan 中唯一未完成项。

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
├── config.py                  # Pydantic Settings(LLMConfig, ExecutionConfig, ServerConfig, RAGConfig) + API key 占位符强校验(P5-I)
├── config_loader.py           # YAML 配置加载(cities.yaml, sources.yaml,带 lru_cache)
├── db_schema.py               # Schema Registry:7 个 SQLite DB 集中管理(替代 Alembic),含 audit_log 表(P5-I)
├── events.py                  # 事件总线(EventBus + EventType)
├── observability/             # P5-B:可观测性
│   ├── trace.py               # ContextVar trace_id(uuid4 hex[:12]) + 跨调用串联
│   └── logger.py              # JSON formatter,读 LOG_FILE,data/logs/app.log 滚动落盘
├── utils/                     # P5-I:通用工具
│   └── pii.py                 # phone/email/id_card/bank_card/address 5 类脱敏 + mask_pii_in_dict 递归
├── server/                    # HTTP 服务(P2-余 拆分产物)
│   ├── app.py                 # RoutedRequestHandler + init_app() + create_handler + SIGTERM graceful(P5-J 待做)
│   ├── router.py              # Route dataclass + RouterRegistry + auth_required 真实落地(P5-D)
│   ├── errors.py              # 统一 JSON 错误响应 + APIError + 错误码→HTTP 状态映射(P5-E)
│   ├── middleware/            # P5-I:中间件
│   │   ├── rate_limit.py      # 滑动时间窗 + Deque,60 req/60s/IP,支持 X-Forwarded-For
│   │   └── audit.py           # record_audit / query_audit,detail 自动 PII 脱敏,失败不阻塞主路径
│   └── routers/               # 13 路由,按资源拆 8 个文件
│       ├── system.py          # /api/health, /api/ready, /api/metrics, /api/chat, /api/chat/enhanced
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
│   ├── memory/                # 三层记忆(短+工作+长,P4-H + P5-G 持久化/向量检索)
│   │   ├── short_term.py      # 短期(P5-G:SQLite-backed,data/short_term.db,公共 API 不变)
│   │   ├── working.py         # 工作记忆(P4-H:per-user workspace + 同名覆盖检测)
│   │   ├── memory_agent.py    # P4-H:级联召回(短→工作→长,先用免费的)
│   │   ├── long_term.py       # 长期(SQLite + WAL,P5-G 加 embedding BLOB 向量检索 + LIKE 兜底)
│   │   └── consolidation.py   # 整合机制(策略模式,P5-G 加 set_message_count 覆盖式修复漂移)
│   ├── knowledge/             # 知识库管理 + 增量更新器
│   ├── rag/                   # RAG 引擎(混合:语义+BM25)+ GraphRAG
│   │   ├── rag_engine.py      # RAGEngine(P4-E 单例,P5-H 异步 rebuild_index + /api/rag/status)
│   │   ├── vector_store.py    # ChromaDB PersistentClient(P5-H Windows 持久化)/FAISS/内存,P4-G 修正 score
│   │   ├── graphrag.py        # GraphRAG 引擎(实体/关系提取 + 多跳推理)
│   │   └── rag_subscriber.py  # 订阅 KNOWLEDGE_UPDATED 重建索引
│   ├── user_profile/          # 画像 + 行为追踪 + 推荐
│   │   ├── user_profile.py    # UserProfileManager
│   │   ├── profile_graph.py   # UserProfileGraph(P4-C 接入,P4-G 加去重)
│   │   ├── persistence.py     # 行为事件/目标/成就/碳足迹持久化层(P4-C + P5-I PII 脱敏)
│   │   ├── behavior_tracker.py
│   │   ├── goal_tracker.py
│   │   ├── achievement_system.py
│   │   ├── carbon_footprint.py
│   │   ├── dynamic_updater.py # analyze_message → detected_interests/action_reports
│   │   └── personalized_recommender.py  # 含 augment_with_rag(P4-F.3)
│   ├── policy/                # 政策更新(P4-E 实爬 httpx+BS4)
│   ├── tools/                 # 工具抽象(BaseTool, ToolRegistry, ToolExecutor)
│   ├── planner/               # 任务规划(TaskDecomposer, Planner/ReActPlanner)
│   ├── scheduler.py           # APScheduler 后台调度(P4-A + P5-F 补全 decay/consolidate/RAG 重建)
│   ├── conversation_store.py  # 会话单例(P4-B.5)
│   └── graph/                 # LangGraph 工作流
│       ├── state.py           # AgentState 状态定义
│       ├── nodes.py           # 6 节点 + 软过滤 + 画像回写(P4-F/P4-G)
│       └── graph.py           # 工作流图(P4-A 挂 SqliteSaver + P4-G 补 ReAct 前置节点)
├── feedback/                  # 反馈管理
│   ├── feedback_manager.py    # FeedbackManager(publish FEEDBACK_RECEIVED,P5-I PII 脱敏)
│   └── profile_subscriber.py  # 订阅反馈事件回流画像
└── auth/                      # 账户管理(账号 + 会话)
    └── account_manager.py     # bcrypt/PBKDF2 双算法(P5-I 审计无明文)

tests/
└── eval/
    └── golden_set.jsonl       # P5-G:50 条检索评估(碳交易/CCER/政策/出行/分类/足迹/认证/省级/适应/补贴),slug 稳定
scripts/
├── doctor.py                  # 项目健康自检(整合 3 个 .bat,P5-I 后 fix)
├── refresh_kb.py              # 知识库半自动策展工作流(KB-v2 后)
├── eval_retrieval.py          # P5-G:hit_rate@5 / MRR@10 / NDCG@10 评估脚本,exit 0/1 CI gate
├── analyze_raw_sources.py     # 政策源 HTML 标题/正文/链接/政策链密度分析
└── agent.bat                  # 整合的启动入口
docs/
├── API.md                     # P5-I:35+ 端点表 + 鉴权 + 限流 + 错误码 + 审计触发条件
├── SECURITY.md                # P5-I:PII + 密码 + 密钥 + 限流 + 审计 + TLS + 已知限制 6 维度
├── RUNBOOK.md                 # P5-J 待做:磁盘满 / ChromaDB 损坏 / DB 锁 / OOM 4 故障场景
└── DEVELOPER.md               # P6 待做:架构图 + 添加新 provider 指南
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
- 7 个 SQLite DB 集中管理(accounts, user_profiles, feedback, policy_updates, long_term_memory, behavior_tracker, **short_term**)
- **P5-I**:`audit_log(id, user_id, action, target, ip, ua, created_at)` 表共享在 `accounts.db`,6 类敏感操作(login/chat_enhanced/profile 等)落审计
- **P5-G**:`user_memories` 加 `embedding BLOB` 列,`_migrate_existing_columns` 幂等 ALTER
- **P5-G**:`conversations` / `conversation_meta` 表在 `short_term.db`,写穿持久化 STM
- `init_all_schemas()` 幂等初始化(WAL 模式)
- 后续切换到 Alembic 时,`SCHEMAS` 即初始 migration 起点

**`src/observability/trace.py` - 调用链追踪(P5-B)**
- `ContextVar` 持有 `trace_id`(uuid4 hex[:12]),LLM 调用入口自动生成,失败可定位
- `with_trace(handler)` 装饰器串联多节点调用,`/api/metrics` 与日志条目都能看到同一 trace_id
- `current_trace_id() / set_trace_id() / clear_trace_id()` 公共 API

**`src/observability/logger.py` - 结构化 JSON 日志(P5-B)**
- `JSONFormatter` 输出 trace_id / level / timestamp / module / message 5 字段
- 启动时 `logging.basicConfig(filename=LOG_FILE, level=LOG_LEVEL)`,`data/logs/app.log` 滚动落盘
- 替代 P4-F 前散落的 `print("[WARN] ...")` 40+ 处(P5-F 全量收尾)

**`src/utils/pii.py` - PII 脱敏(P5-I)**
- `mask_phone(13800001234) → "138****1234"`
- `mask_email(a@b.com) → "a***@b.com"`
- `mask_id_card / mask_bank_card / mask_address` 5 类基础脱敏
- `mask_pii_in_dict(d, keys=("phone", "email", ...))` 递归 dict 节点
- `feedback_manager` / `persistence` / `audit` 落库前自动调用,失败回退到原值(不阻塞主路径)

**`src/server/middleware/rate_limit.py` - 限流(P5-I)**
- 滑动时间窗 + `collections.deque`,默认 60 req/60s/IP
- 支持 `X-Forwarded-For`(反代场景),按客户端 IP 隔离
- `_dispatch` 早于鉴权执行(防暴力),超限返 429

**`src/server/middleware/audit.py` - 审计日志(P5-I)**
- `record_audit(user_id, action, target, ip, ua, detail)` 落 `audit_log` 表
- `detail` 字段自动 PII 脱敏
- 异步写(不阻塞主路径),失败静默(PII 错误不影响业务)
- `/api/auth/login` / `/api/chat/enhanced` / `/api/profile` 等 6 类端点必审计

**`src/server/errors.py` - 统一错误处理(P5-E)**
- `APIError` 异常类 + 错误码→HTTP 状态映射(`AUTH_REQUIRED=401` / `NOT_FOUND=404` / `INTERNAL=500` / `LLM_UNAVAILABLE=503`)
- `_dispatch` `except APIError` 返结构化 JSON,其他异常记录 traceback 到 `data/logs/error.log`,**只**对客户端返 `{code: "INTERNAL", message: "服务暂时不可用"}`(不泄栈)

**`src/llm/client.py` - 6 provider 统一契约(P5-A)**
- `LLMResponse` dataclass 唯一契约:`content` / `latency_ms` / `request_id` / `error` / `usage`
- 6 provider 全部 `chat.completions.create(..., timeout=30, max_retries=2)`
- 删除 P5-C 前 `CURL_CA_BUNDLE=''` 全局污染,改本地 `httpx.Client(verify=False)`(仅 `INSECURE_SKIP_VERIFY=true` 生效)
- `tenacity` 装饰器统一重试:3 次 + 1s→2s→4s 指数退避
- 入口生成 `trace_id`,`logger.info("llm_call", extra={trace_id, model, latency_ms, usage, error})`

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

**`src/memory/long_term.py` - 长期记忆(P4-B.3 + P5-G 向量检索)**
- `user_memories` 表的 `last_accessed` / `access_count` 在 `get_recent_memories` / `search_memories` 时自动更新
- **P5-G**:`embedding BLOB` 列(懒加载 `_compute_embedding_blob`,embedder 不可用时 NULL 降级)
- **P5-G**:`search_memories` 新算法 = 向量余弦 top-20 + LIKE 兜底,合并去重按 score 排序
- `decay_importance(half_life_days=30)` 按半衰期公式 `rate = 0.5 ** (days / half_life)` 衰减
- 兼容旧 `decay_importance(decay_rate=0.95)` 调用

**`src/memory/short_term.py` - 短期记忆(P4-B + P5-G SQLite 持久化)**
- **P5-G**:完整重构 SQLite-backed,`data/short_term.db` 写穿(每 add_message 一次 commit)
- 公共 API 完全不变(`add_message` / `get_conversation_history` / `search_conversations` / `cleanup_expired` 等 7 个读方法签名稳定)
- `self.conversations` 内部改名 `self._cache`,`self.metadata` 仍为公共 Dict(scheduler 可读)
- WAL 模式 + `busy_timeout=5000`,1 写 < 1ms
- `get_short_term_memory` 双检锁单例仍可用

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

**`src/rag/rag_engine.py` - RAG 引擎 + 单例(P4-E + P5-G 评估 + P5-H 异步重建)**
- `get_rag_engine(config=None)` 双检锁单例(供 RAG 订阅者直接调 rebuild_index)
- `reset_rag_engine()` 测试用
- **P5-G**:`tests/eval/golden_set.jsonl` 50 条评估,`scripts/eval_retrieval.py` 输出 `hit_rate@5 / MRR@10 / NDCG@10`
- **P5-H**:`rebuild_index` 改后台线程 + `Event` 通知,`/api/rag/status` 查 `progress 0~100%`
- **P5-H**:`add_documents(paths)` / `delete_documents(paths)` 增量 upsert,替代全量 `rebuild_index`
- `RAGConfig.min_similarity=0.0`(P4-G:MiniLM 距离大,0.3 会漏检)

**`src/rag/vector_store.py` - 向量存储(P4-G 修复 + P5-H Windows 持久化)**
- ChromaDB 路径:`score = 1.0/(1.0+distance)`(兼容非归一化向量)
- **P5-H**:改用 `chromadb.PersistentClient(path="data/vector_db")`,Windows 加 `Settings(anonymized_telemetry=False, allow_reset=False)`
- FAISS 路径:同样的倒数归一化
- Inmemory 路径:余弦相似度(已正确)

**`src/server/routers/system.py` - 健康检查 + 指标(P5-B/E)**
- `GET /api/health` 真探活:SQLite `SELECT 1` + Chroma `collection.count()` + APScheduler 状态 + `ModelStats.last_latency_ms`
- `GET /api/ready` K8s readiness probe(轻量级,只查 DB)
- `GET /api/metrics` JSON:`total_calls / avg_latency_ms / p95 / total_tokens / error_rate` + 每 provider 分布
- 任一探活失败返 503(负载均衡可剔除)

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

- `config/settings.yaml`: LLM 提供商、向量数据库、知识库路径、`LOG_LEVEL` / `LOG_FILE`(P5-B)、`LLM_TIMEOUT_SECONDS` / `LLM_MAX_RETRIES`(P5-C)
- `config/cities.yaml`: 城市配置(默认北京,识别 10 个主要城市)— P2-余 外部化
- `config/sources.yaml`: 政策源 URL(KB-v4:20 个,`disabled_sources` 8 个)— P2-余 外部化
- `.env`: API 密钥(9 个,**P5-I 启动强校验**非占位符 `__SET_ME__` / `sk-xxx`,ENV=production 时改 error)
- `USE_LANGGRAPH=true`: 启用 LangGraph 工作流(P2 合并为 `execution_mode` 枚举)
- `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`: CORS 白名单(P5-J 待收紧为生产域名)
- `INSECURE_SKIP_VERIFY=true`: LLM SSL 验证豁免(P5-C,默认 false)

## 数据目录

- `knowledge_base/`: Markdown 格式知识文档(basic/policy/guide 三类,150 文档块,KB-v7)
  - `policy/national_policy.md` 全国级
  - `policy/beijing_low_carbon.md` 等(地区级,KB-v2 起)
  - `policy/2024_carbon_market_regulation.md` / `2024_trade_in_action.md`(2024-2025 高时效)
  - `regional/shanghai_low_carbon.md` / `shenzhen_low_carbon.md`
  - `basic/carbon_footprint_standard.md` / `guide/2024_2025_subsidies.md`
- `data/vector_db/`: ChromaDB 向量数据库(**PersistentClient**,P5-H Windows 持久化)
- `data/accounts.db`: 账号与会话 + **audit_log 表(P5-I)**
- `data/user_profiles.db`: 画像(JSON + graph 子字段,P4-C)
- `data/feedback.db`: 消息反馈
- `data/policy_updates.db`: 政策库 + update_logs
- `data/long_term_memory.db`: 长期记忆 + user_preferences + **embedding BLOB(P5-G)**
- `data/behavior_tracker.db`: 行为事件 + goals + achievements + carbon(P4-C)
- `data/short_term.db`: **P5-G 短期记忆 SQLite 持久化**(原内存)
- `data/langgraph_checkpoints.db`: LangGraph 状态快照(P4-A)
- `data/logs/`: **P5-B 结构化 JSON 日志**(app.log / error.log 滚动)

## API 端点(35+ 路由)

**鉴权状态(P5-D 半完成)**:P5-D 写了 `with_auth` 中间件 + `_dispatch` 接入 + `AccountManager.verify_token` + 17 个 `test_auth_e2e.py` 端到端测试,**基础设施就绪**;但 `routers/*.py` 30+ 个 `add_route` 调用全部显式 `auth_required=False`(保护测试 `test_e2e_legacy_endpoints_still_work` 期望 `/api/policy/summary` 等老 API 无 token 也能通)。**鉴权**只在以下场景生效:`/api/auth/*` 自身会话校验、P5-D 测试 fixture 注入 token、P5-I 启动时密钥占位符强校验。**P6 计划**:`router.add_route` 默认 `auth_required=True` 后,把"敏感"路由(`/api/chat*` / `/api/profile*` / `/api/feedback*` / `/api/memory*` / `/api/recommendations`)切到 `True`,加 `test_e2e_real_auth.py` 全量覆盖。

**限流**(P5-I 全部生效):所有端点 60 req/60s/IP,支持 X-Forwarded-For,超限返 429(实测第 59 次触发)。

**审计**(P5-I 全部生效):6 类写敏感读操作记录到 `audit_log` 表 — `login` / `chat_enhanced` / `profile` / `feedback` / `policy/sync` / `memory`。

**错误响应**(P5-E 全部生效):统一 `{code, message}` JSON,不再泄栈。

### 路由表(35+)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | Web 界面 |
| `/api/health` | GET | 真探活(SQLite + Chroma + Scheduler + LLM 延迟 + 磁盘,P5-E) |
| `/api/ready` | GET | K8s readiness probe(P5-E) |
| `/api/metrics` | GET | LLM 调用指标 `total_calls / p95 / total_tokens / error_rate`(P5-B) |
| `/api/rag/stats` | GET | RAG 状态(enabled + engine ok/not_initialized) |
| `/api/rag/status` | GET | RAG 异步重建进度 0~100%(P5-H) |
| `/api/knowledge/stats` | GET | 知识库统计(150 文档块,KB-v7) |
| `/api/knowledge/query` | POST | 知识库查询 |
| `/api/knowledge/reload` | POST | 强制 RAG 重建(后台线程 + 进度查询) |
| `/api/policy/latest` | GET | 最新政策(limit=10) |
| `/api/policy/summary` | GET | 政策摘要 |
| `/api/policy/check-updates` | POST | 检查政策更新 |
| `/api/auth/register` | POST | 用户注册(bcrypt/PBKDF2) |
| `/api/auth/login` | POST | 登录(失败限流 + 审计) |
| `/api/auth/logout` | POST | 登出 |
| `/api/auth/check` | POST | 验证会话 |
| `/api/auth/session` | POST | 会话详情 |
| `/api/chat` | POST | 基础聊天 |
| `/api/chat/enhanced` | POST | 增强聊天(RAG+个性化) |
| `/api/conversation/reset` | POST | 重置对话 |
| `/api/conversation/history` | POST | 对话历史 |
| `/api/conversation/{conv_id}` | GET | 对话历史(GET) |
| `/api/recommendations` | POST | 个性化推荐(基于画像) |
| `/api/profile/{user_id}` | GET | 获取用户画像(**带 user_id**,正则前缀 `^/api/profile/`) |
| `/api/personalization/{user_id}` | GET | 个性化上下文(GET) |
| `/api/personalization/context` | POST | 个性化上下文(POST) |
| `/api/stats/{user_id}` | GET | 用户统计 |
| `/api/onboarding/questions` | GET | 获取引导问题(8 步问卷) |
| `/api/onboarding/status` | POST | 引导状态 |
| `/api/onboarding/start` | POST | 开始引导 |
| `/api/onboarding/answer` | POST | 回答引导问题 |
| `/api/user/register` | POST | 注册用户 |
| `/api/user/update` | POST | 更新用户画像 |
| `/api/feedback` | POST | 提交反馈(PII 脱敏) |
| `/api/feedback/message` | POST | 消息反馈详情 |
| `/api/feedback/stats` | POST | 反馈统计 |
| `/api/feedback/history` | POST | 用户反馈历史 |
| `/api/feedback/negative` | POST | 最近负面反馈 |
| `/api/settings/api-key` | POST | 保存 API Key |

## 重构进度(P0–P5 共 26 commit,P5-A→I 全部完成,P5-J 待做)

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
| `cd9c0ce` | P4-H | **三层记忆补齐** — 工作记忆(`working.py`)+ 级联召回(`memory_agent.py`)+ 短→工作→长 整合 + LLM prompt 注入 |
| `860bd5c` | P5-A.1 | LLMResponse 契约加 `latency_ms` / `request_id` / `error` 字段 |
| `a16f652` | P5-A.2 | 6 provider + Bayesian 路由器统一返回 `LLMResponse` |
| `f33db17` | P5-B | LLM 可观测性 — `trace_id` + 结构化 JSON 日志 + `/api/metrics` |
| `559f833` | P5-C | LLM 可靠性硬化 — 超时 / 重试 / SSL 修复,删除全局 `CURL_CA_BUNDLE` 污染 |
| `7fe3ac6` | P5-D | 鉴权 + 路由统一(`auth_required` 真实落地,`with_auth` 中间件) |
| `86fbb35` | P5-E | 错误处理 + 健康检查(`/api/health` 真探活 + `/api/ready` K8s readiness) |
| `965ca9d` | P5-F | 日志系统补全 + 调度补全(`decay_importance` 真定时) + 启动后台 RAG 重建 |
| `611410b` | P5-G | 检索质量评估(`tests/eval/golden_set.jsonl` + `scripts/eval_retrieval.py`)+ STM 持久化 + LTM 向量检索 |
| `1635a8f` | P5-H | 知识库合并 + ChromaDB Windows 持久化(`PersistentClient`) + 异步重建 |
| `7c37713` | **P5-I** | 安全/合规/PII 脱敏 + 限流(`rate_limit.py`)+ 审计日志 + 文档三件套 — HEAD |

**P4 阶段成果**:
- 65 个 P4 单元/E2E 测试全过(`pytest tests/test_p4*.py -v`)
  - P4-A~G 共 50 + P4-H 新增 15(working memory 单例/覆盖检测/cross-session/级联召回/晋升 LTM/heartbeat)
- agent 端到端可运行:`chat_enhanced` 知识查询返回 4 个推荐(1 RAG + 3 静态)+ 3 个 knowledge_refs + 685 chars RAG context
- 多轮对话画像图谱正确更新(兴趣+行为,边/节点去重)
- 知识库按地区软过滤(北京用户→北京政策加分)
- 政策实爬 + RAG 订阅者自动重建索引
- **P4-H** 三层记忆(短+工作+长)真正打通:workspace 命名空间 + 同名 key 覆盖检测 + OpenClaw 风格 heartbeat(每 4h 清理过期 + 晋升高 importance)

**P5 阶段成果(2026-06)**:
- **可观测性(P5-B/F)**:每次 LLM 调用都有 `trace_id`(ContextVar + uuid4 hex[:12]),`GET /api/metrics` 返回 P50/P95 延迟 + token 用量;`data/logs/app.log` JSON formatter 滚动落盘
- **可靠性(P5-C)**:6 provider 全部 `timeout=30` + `max_retries=2` + `usage` 字段统一,删除 `CURL_CA_BUNDLE=''` 全局污染(`INSECURE_SKIP_VERIFY=true` 显式开启)
- **鉴权(P5-D)**:`auth_required` 不再装饰字段,35+ 端点 100% 走 `with_auth` 中间件,`Bearer <session_id>` 验证,过期 401
- **错误处理(P5-E)**:`APIError` 异常类 + 错误码→HTTP 状态映射表,异常不泄栈(只返 `{code, message}`),`/api/health` 真探活 SQLite + Chroma + Scheduler + `ModelStats.last_latency_ms`
- **检索质量(P5-G)**:50 条 golden set(slug 稳定),`hit_rate@5 / MRR@10 / NDCG@10` 三 metric 评估,curated 子集 ≥ 60% 视为通过;STM 写穿 SQLite(`data/short_term.db`),LTM 加 `embedding BLOB` 列支持余弦相似度 + LIKE 兜底
- **持久化(P5-H)**:ChromaDB 改用 `PersistentClient`,Windows 重启不丢;`rebuild_index` 后台线程 + `/api/rag/status` 进度查询;`md5(html[:20000])` 改分块 hash
- **安全合规(P5-I)**:PII 5 类脱敏(phone/email/id_card/bank_card/address)落库前自动打码,60 req/60s/IP 滑动窗口限流(支持 XFF),`audit_log` 表记录 user_id/action/target/ip/ua 6 类敏感操作,启动时强校验 9 个 API key 不为占位符
- **文档(P5-I)**:`docs/API.md`(35+ 端点)/ `docs/SECURITY.md`(PII+密钥+限流+审计+TLS+已知限制)/ `CHANGELOG.md`(P0–P5 全部 26 commit 摘要)
- **测试**:33 个测试文件,全量回归 **112 passed**;`test_p5i_security.py` 19 个(覆盖 PII/限流/审计/密钥)+ `test_p5g_*` 11 个 + `test_p5h_kb_rag.py`

**KB-v2→v7 知识库迭代(2026-06)**:
- **v2**:`config/sources.yaml` 7 源实测可通(新浪 ESG/中国能源报/财新/人民网/中国循环经济协会/IPCC/IEA);政府站(.gov.cn)经实测**全部 SSL 失败**(港/海外 IP 拒绝)→ 8 个源记入 `disabled_sources` 留档;`PolicyUpdater.check_updates()` 错误可见性修复;知识库 7 → 13 markdown,RAG 32 → 67 文档块
- **v3**:扩 3 个专题(广东 / 欧盟 CBAM / 北京 1.1K→5.2K)
- **v4**:拓源大陆 IP 实测,7 → 20 政策源
- **v5**:北京 2026 政府详情页 → 3 篇真实政策 markdown
- **v6**:递归抓 `mee.gov.cn` 双碳列表 → 4 篇国家级原文
- **v7**:CCER 方法学扩围 + 省级温室气体清单 + 适应气候变化进展 → **150 文档块**,RAG 召回 6/6 全命中
- `scripts/refresh_kb.py` 知识库半自动策展工作流

**P5-I 后的 fix/feat**:
- `c1804b1` 真实 API 接入修复(MiniMax + 高德 + 和风 API 调用路径打通)
- `bf004c7` 和风天气 403 → Open-Meteo 免费实时天气替换
- `84c3e7d` 高德 geocode 回退顺序(默认 city 优先,跨城兜底)
- `776d201` 出行规划多因素评分(碳排+费用+时长+天气)
- `6835eea` 3 个 `.bat` 整合为 `agent.bat` + `scripts/doctor.py`
- `6d515bc` BayesianModelRouter 死锁 + HumanMessage 兼容(让 CI 不再 hang)

**当前计划(2026-06)**: 详见 `~/.claude/plans/bug-agent-groovy-flute.md`(P0–P5-I 完成,**P5-J 部署/SRE 收口**待做:2 天交付 Dockerfile / docker-compose / SIGTERM graceful / systemd + nssm / nginx 反代 / `docs/RUNBOOK.md`)。
