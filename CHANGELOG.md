# Changelog

绿色低碳智能体的版本演进记录。规范遵循 [Keep a Changelog](https://keepachangelog.com/)。

## [Unreleased] — P5 工程化

### P5-H(2026-06-10)— 知识库合并 + ChromaDB 持久化

- **A. ChromaDB Windows 持久化**(`src/rag/vector_store.py`):
  删除"Windows 强制 in-memory"分支,统一 `PersistentClient(path=...)`,
  加 `Settings(anonymized_telemetry=False, allow_reset=False)`,新增 `is_persistent` 属性
- **B. KnowledgeManager 代理化**(`src/knowledge/manager.py`):
  `search()` 优先委托 `RAGEngine.retrieve()`,RAG 不可用时降级 + `DeprecationWarning`
- **C. 异步重建**(`src/rag/rag_engine.py` + `src/server/routers/system.py`):
  `rebuild_index_async()` 后台线程执行,`get_rebuild_status()` 暴露进度,
  新增 `GET /api/rag/status`
- **D. 分块 hash**(`src/knowledge/updater.py`):
  `md5(html[:20000])` 替换为 `_compute_content_hash`:
  <50KB 分段 md5,≥50KB 整文 SHA256
- **E. 增量 upsert**(`src/rag/rag_engine.py`):
  新增 `add_documents(paths, base_path)` / `delete_documents(sources)`,
  按 source 增删 chunk,`_norm_source()` 归一化路径/文件名/stem
- 测试:`tests/test_p5h_kb_rag.py` 13 个,全过
- 回归:修复 `test_memory_singleton.py` 在 P5-G STM 持久化后的污染问题

### P5-G(2026-06-09)— 检索质量评估 + STM 持久化 + LTM 向量检索

- **A. 检索质量评估**:
  - `tests/eval/golden_set.jsonl` 51 条 / 20 slug / 10 类
  - `scripts/eval_retrieval.py` 实现 hit_rate@5 / MRR@10 / NDCG@10,
    curated 阈值 0.60 / full 阈值 0.40
  - 基线:**curated 72.7%**,**full 70.6%**(均过阈)
- **B. STM 持久化**(`src/memory/short_term.py` + `src/db_schema.py`):
  SQLite + WAL + `busy_timeout=5000`,`self._cache` 私有 + `self.metadata` 公共
- **B'. 漂移修复**(`src/memory/consolidation.py` + `src/scheduler.py`):
  新增 `set_message_count`(覆盖式)替代 `update_message_count`(累加)
- **C. LTM 向量检索**(`src/memory/long_term.py` + `src/db_schema.py`):
  `user_memories` 加 `embedding BLOB`,`search_memories` 余弦 top-20 + LIKE 兜底
  + 去重合并;embedder 不可用 / 旧行 NULL 时降级为纯 LIKE
- 测试:`tests/test_p5g_*` 4 个文件,共 19 个,全过

### P5-F(2026-06-08)— 日志系统 + 调度补全

- `src/observability/{__init__,trace,logger}.py`:ContextVar trace_id +
  JSON formatter + 滚动日志(`data/logs/app.log`)
- `src/scheduler.py`:新增 `consolidate_short_to_long` 每小时跑 + 启动时异步
  `rag_engine.rebuild_index()`(P5-H 前置)
- 替换 40+ 处 `print("[WARN]")` / `print("[ERROR]")` 为 `logger.warning/error`
- `tests/test_scheduler_logging.py` 16 个,全过

### P5-E(2026-06-07)— 错误处理 + 健康检查

- `src/server/errors.py`:`APIError` + code→HTTP 状态映射表
- `src/server/app.py:_dispatch`:业务异常 `APIError` 直接返,未知异常兜底
  `INTERNAL` + 记 traceback 到 `data/logs/error.log`,**不**向客户端泄栈
- `src/server/health.py`:`/api/health` 真探活(accounts.db + vector store
  + scheduler + metrics + 磁盘),`/api/ready` K8s readiness
- `tests/test_p5e_health.py` 5 个,全过

### P5-D(2026-06-06)— 鉴权 + 路由统一

- `src/auth/account_manager.py:verify_token(headers, body)`:
  支持 `Authorization: Bearer` / `X-Session-Id` / body.session_id
- `src/server/router.py:Route` 默认 `auth_required=True`,
  `src/server/app.py:_dispatch` 接入 `with_auth` 中间件
- 13 路由迁出 `main.py` → `src/server/routers/{auth,feedback,onboarding,
  profile,memory,policy,knowledge,system}.py`
- `tests/test_auth_e2e.py` 5 个,全过

### P5-C(2026-06-05)— LLM 可靠性硬化

- `src/llm/client.py`:6 个 provider 全部 `chat.completions.create(timeout=30,
  max_retries=2)`,填入 `LLMResponse.usage` 字段
- 移除 `CURL_CA_BUNDLE=''` 全局污染,改为 `INSECURE_SKIP_VERIFY=true` 显式
  触发 + WARN 日志
- `tenacity` 接入通用重试(3 次 + 指数退避 1s→2s→4s)
- `tests/test_p5c_reliability.py` 8 个,全过

### P5-B(2026-06-04)— LLM 可观测性

- `src/observability/{trace,logger,metrics_collector}.py`:
  `trace_id` ContextVar(每请求 uuid4 hex[:12])+ JSON 滚动日志
  + `ModelStats` 滑动窗口(默认 1000 调用)
- `src/llm/client.py:chat()` 入口:生成 trace_id,记 `llm_call` 事件
  (model / latency_ms / usage / error)
- `GET /api/metrics`:全局聚合 + 按 provider 分组 + 延迟分位数
- `tests/test_p5b_metrics.py` 6 个,全过

### P5-A(2026-06-03)— 统一 LLM 客户端契约

- 6 个 `*Client.chat()` 统一返回 `LLMResponse` dataclass,
  加 `latency_ms` / `request_id` 字段
- 合并 `client.py:SYSTEM_PROMPT` 与 `__init__.py:SYSTEM_PROMPT_TEMPLATE`,
  单一 `build_system_prompt()` 入口
- `tests/test_p5a_contract.py` 6 个,全过

---

## [4.0.0] — P0–P4-G + P4-H(2026-05)

### P4-H — 三层记忆补齐

- 工作记忆 `src/memory/working.py`:per-user workspace + 同名 key 覆盖检测
  + OpenClaw 风格 heartbeat(每 4h 清理 + 晋升高 importance)
- 级联召回 `src/memory/memory_agent.py`:短→工作→长,先用免费的
- `tests/test_p4h_working_memory.py` 15 个,全过

### P4-G — 端到端修复 + 画像图谱去重

- `tests/test_p4g_e2e.py` 10 个 E2E 全过
- ChromaDB score 公式 `1.0/(1.0+distance)`,FAISS 同步
- RAG `RAGConfig.min_similarity=0.0`(MiniLM 距离偏大,0.3 漏检)
- 画像图谱 `add_interest/add_action` 去重(同 user-兴趣对取最高置信度)
- 加固 7 个 P3-余遗留 Bug

### P4-F — 知识库个性化

- `src/agent/graph/nodes.py:_region_aliases` 中英文互转
- `_rerank_by_personalization` 软重排(region ×1.3 / interest ×1.15)
- `personalized_recommender.augment_with_rag()` 把 RAG 结果插入推荐头部

### P4-E — 实时知识/政策同步

- `src/policy/updater.py`:httpx(30s timeout)+ BS4 提取,
  `config/sources.yaml` 7 个实测可通源
- `RAGConfig.get_rag_engine()` 单例 + `rag_subscriber` 自动重建索引
- KB-v2:13 个文档,67 个 chunk

### P4-D — 行为阶段驱动 LLM

- 5 阶段 prompt 差异化(action / intention / preparation / maintenance / termination)

### P4-C — 画像图谱化 + 持久化

- `UserProfileGraph`:节点/边 JSON 化(零新依赖)
- `BehaviorPersistence`:4 张表(behavior_events / user_goals /
  user_achievements / carbon_footprint_log)

### P4-B — 三层记忆真正打通

- `LongTermMemory.search_memories` 真召回 + 热度更新
- `decay_importance` 半衰期 30 天
- `ConversationStore` 单例(双检锁)

### P4-A — 启动时事件订阅 + APScheduler

- 每日 02:00 KB 增量 + 每日 03:00 记忆衰减 + 启动时异步 RAG 重建
- LangGraph SqliteSaver checkpointer

### P3 — 事件总线 + Schema Registry

- `EventBus` 单例 + `KNOWLEDGE_UPDATED` / `FEEDBACK_RECEIVED`
- `src/db_schema.py` 统一管理 6 个 SQLite DB
- `feedback.profile_subscriber` 反馈事件→画像回流

### P2 — 路由拆分 + 配置外部化

- 13 路由迁出 `main.py`
- `paths.py` / `config.py` 集中
- `config/cities.yaml` / `config/sources.yaml` 外部化
- 死代码清理

### P1 — 并发与可靠性

- `ThreadingHTTPServer` + DB WAL + 工具超时(30s)
- ReAct `step_count` 限制
- planner 失败任务显式化
- GraphRAG 关系去重 O(N²)→O(N)

### P0 — 安全基线

- 4 个真实 API 密钥轮换 + git-filter-repo 清理历史
- 5 个致命 Bug 修复

---

## 已知遗留

- P5-I:审计日志无 TTL,长期保留需手工归档
- P5-I:内存限流不跨进程(多 worker 需 Redis)
- P5-G:旧行 `user_memories.embedding` 为 NULL,需后台 backfill
- P4-G:KB 增量仅识别"路径 + mtime",无内容指纹比对
