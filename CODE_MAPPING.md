# 代码与开题报告对应关系

本文档建立 SPEC.md 章节与核心代码模块的映射，方便论文答辩时快速定位实现位置。

---

## 一、系统架构（SPEC.md 第1-2章）

| SPEC 章节 | 实现位置 | 说明 |
|-----------|---------|------|
| 技术架构概览 | `src/main.py` → `src/server/app.py` | HTTP 入口(委托给 RoutedRequestHandler) |
| HTTP 路由 | `src/server/routers/` | 8 个 router 文件,13 条路由 |
| 路由注册 | `src/server/router.py` | `RouterRegistry` + `Route` dataclass |
| 核心引擎 | `src/agent/core.py` | `GreenAgent` 类,整合所有模块 |
| 意图理解 | `src/agent/intent.py` | `IntentRecognizer` 类 |
| 响应生成 | `src/agent/response.py` + `src/agent/response_mapper.py` | IntentType → response_type 单一映射 |
| LangGraph 架构 | `src/agent/langgraph_agent.py` | StateGraph 替代实现 |
| 路径管理 | `src/paths.py` | PROJECT_ROOT / DATA_DIR / 各 DB 路径 |
| 配置管理 | `src/config.py` + `src/config_loader.py` | Pydantic Settings + YAML 加载 |
| Schema Registry | `src/db_schema.py` | 6 个 SQLite DB 集中管理 |
| 事件总线 | `src/events.py` | EventBus + EventType(订阅/发布) |

---

## 二、核心模块设计

### 2.1 智能体核心引擎

| SPEC 功能 | 代码实现 | 关键方法 |
|-----------|---------|---------|
| 用户意图理解 | `src/agent/intent.py` | `IntentRecognizer.recognize()` |
| 对话策略管理 | `src/agent/core.py` | `GreenAgent.chat_enhanced()` |
| 响应生成与优化 | `src/agent/response.py` | `ResponseGenerator.generate_response()` |
| LLM增强响应 | `src/agent/response.py` | `ResponseGenerator.generate_with_llm()` |
| Prompt构建 | `src/llm/client.py` | `build_chat_prompt()` |

### 2.2 知识库系统

| SPEC 功能 | 代码实现 | 说明 |
|-----------|---------|------|
| 知识分类加载 | `src/knowledge/manager.py` | `KnowledgeManager` 类 |
| 向量检索(RAG) | `src/rag/rag_engine.py` | `RAGEngine` 类 |
| 嵌入生成 | `src/rag/embedder.py` | `Embedder` 接口 |
| 向量存储 | `src/rag/vector_store.py` | `VectorStore` 接口 |
| 混合检索 | `src/rag/retriever.py` | `HybridRetriever` 类 |
| 知识库文档 | `knowledge_base/` | 6个Markdown文档 |

**RAG流程图**：
```
用户查询 → RAGEngine.retrieve()
           ├→ Embedder.encode() → ChromaDB语义检索
           └→ BM25Retriever 关键词检索
           └→ HybridRetriever 加权融合
           └→ 返回 RetrievalResult[]
```

### 2.3 长短期记忆系统

| SPEC 功能 | 代码实现 | 说明 |
|-----------|---------|------|
| 短期记忆 | `src/memory/short_term.py` | `ShortTermMemory` 类，内存存储 |
| 长期记忆 | `src/memory/long_term.py` | `LongTermMemory` 类，SQLite持久化 |
| 偏好存储 | `src/memory/long_term.py` | `update_preference()` 方法 |
| 记忆检索 | `src/memory/long_term.py` | `get_recent_memories()` 方法 |

**记忆架构**：
```
工作记忆 (Working Memory)
   └→ 最近3-5轮对话上下文 → agent/core.py 内存变量

短期记忆 (Short-Term)
   └→ 会话级对话历史 → memory/short_term.py (内存，TTL)

长期记忆 (Long-Term)
   └→ 用户画像 + 偏好 → memory/long_term.py (SQLite持久化)
```

### 2.4 用户画像与个性化推荐

| SPEC 功能 | 代码实现 | 说明 |
|-----------|---------|------|
| 用户画像管理 | `src/user_profile/user_profile.py` | `UserProfileManager` 类 |
| 画像数据库 | `data/user_profiles.db` | SQLite存储 |
| 动态画像更新 | `src/user_profile/dynamic_updater.py` | `DynamicProfileUpdater` 类 |
| 个性化推荐引擎 | `src/user_profile/personalized_recommender.py` | `PersonalizedRecommendationEngine` 类 |
| 用户引导流程 | `src/agent/core.py` | `start_onboarding()` / `process_onboarding_answer()` |

**画像维度**（共8个维度）：
1. `basic_info` - 年龄/性别/地区/收入/家庭 → `user_profile.py`
2. `eco_profile` - 环保认知/行为阶段/兴趣 → `user_profile.py`
3. `behavior_profile` - 出行/饮食/消费习惯 → `user_profile.py`
4. `communication_style` - 沟通风格 → `user_profile.py`
5. `preferences` - 内容深度/响应长度/语气 → `user_profile.py`
6. `preference_learning` - 确认/推断的兴趣 → `dynamic_updater.py`
7. `statistics` - 交互统计 → `user_profile.py`
8. `onboarding` - 引导状态 → `user_profile.py`

### 2.5 低碳政策实时更新

| SPEC 功能 | 代码实现 | 说明 |
|-----------|---------|------|
| 政策更新器 | `src/policy/updater.py` | `PolicyUpdater` 类(2026 计划实爬 httpx+BS4) |
| 政策源配置 | `config/sources.yaml` | P2-余 外部化 |
| 政策数据库 | `data/policy_updates.db` | SQLite(policies + update_logs) |
| 政策摘要 | `src/policy/updater.py` | `generate_policy_summary()` 方法 |
| 政策→RAG 事件 | `src/policy/updater.py` → `src/rag/rag_subscriber.py` | 2026 计划(P4-E) |

### 2.6 用户引导流程(Onboarding)

| SPEC 功能 | 代码实现 | 说明 |
|-----------|---------|------|
| 引导路由 | `src/server/routers/onboarding.py` | `/api/onboarding/{start,answer,status}` |
| 引导核心 | `src/agent/core.py` | `start_onboarding()` / `process_onboarding_answer()` |
| 8 步问卷 | `src/user_profile/user_profile.py:701-796` | 年龄/性别/地区/收入/家庭/兴趣/知识/阶段 |

---

## 三、算法/模型方法论

### 3.1 行为阶段模型（Transtheoretical Model）

**理论来源**：Prochaska的跨理论模型(TTM)，将行为改变分为5个阶段。

**代码实现**：`src/user_profile/personalized_recommender.py`

```python
STAGE_STRATEGIES = {
    "无意向": {
        "difficulty_filter": ["easy"],      # 只推荐最简单的行动
        "suggestion_count": 1,
        "focus": "意识唤醒",
        "tone": "鼓励性",
    },
    "意向": {
        "difficulty_filter": ["easy", "medium"],
        "suggestion_count": 2,
        "focus": "动机强化",
        "tone": "积极正面",
    },
    # ... 以此类推
}
```

**论文引用**：可在答辩中说明"行为阶段模型"是心理学中经典的行为改变理论。

### 3.2 Beta-Bernoulli 多臂老虎机（贝叶斯模型路由）

**理论来源**：贝叶斯推断 + 多臂老虎机（Multi-Armed Bandit）

**代码实现**：`src/llm/client.py` 中的 `BayesianModelRouter` 类

**核心原理**：
1. 每个LLM模型的成功率建模为Beta分布：`Beta(α, β)`
2. 初始先验：`Beta(1, 1)`（均匀分布）
3. 每次调用后更新后验：
   - 成功：α += confidence
   - 失败：β += 1
4. 选择时，从各模型的Beta分布中采样，选择采样值最高的模型（Thompson Sampling）

**为什么用贝叶斯**：
- 不需要大量数据就能开始选择
- 后验分布自然编码了不确定性
- 探索（试新模型）和利用（选好模型）的权衡自动完成

**代码位置**：`src/llm/client.py` 第416-853行

### 3.3 混合检索（Hybrid Search）

**理论来源**：信息检索中的混合搜索策略，结合语义检索和关键词检索。

**代码实现**：`src/rag/retriever.py` 的 `HybridRetriever` 类

**核心公式**：
```
hybrid_score = semantic_weight × semantic_similarity + (1 - semantic_weight) × bm25_score
```

**默认配置**：`semantic_weight = 0.6`（60%语义 + 40%关键词）

**论文引用**：可说明这是学术界通用的混合检索方法（参考论文"Hybrid Retrieval"）。

### 3.4 动态画像学习

**代码实现**：`src/user_profile/dynamic_updater.py`

**核心机制**：
1. **兴趣检测**：关键词匹配 + 权重计算
2. **行为阶段检测**：意图词分析（如"准备"、"正在"等关键词）
3. **知识水平检测**：问题复杂度分析（专业术语 vs 基础问题）
4. **行动提取**：正面/负面行动的关键词匹配
5. **反馈学习**：采纳增强兴趣权重，拒绝降低权重

---

## 四、API接口（SPEC.md 第7章）

| 接口端点 | 方法 | 实现位置 | 功能 |
|---------|------|---------|------|
| `/api/health` | GET | `server/routers/system.py` | 健康检查 |
| `/api/chat` | POST | `server/routers/system.py` | 基础对话 |
| `/api/chat/enhanced` | POST | `server/routers/system.py` | 增强对话(RAG+个性化) |
| `/api/auth/register` | POST | `server/routers/auth.py` | 用户注册 |
| `/api/auth/login` | POST | `server/routers/auth.py` | 登录 |
| `/api/auth/logout` | POST | `server/routers/auth.py` | 登出 |
| `/api/profile` | GET/PUT | `server/routers/profile.py` | 获取/更新画像 |
| `/api/onboarding/start` | POST | `server/routers/onboarding.py` | 开始引导 |
| `/api/onboarding/answer` | POST | `server/routers/onboarding.py` | 回答引导问题 |
| `/api/feedback` | POST | `server/routers/feedback.py` | 提交反馈 |
| `/api/knowledge/stats` | GET | `server/routers/knowledge.py` | 知识库统计 |
| `/api/knowledge/query` | POST | `server/routers/knowledge.py` | 知识库查询 |
| `/api/knowledge/reload` | POST | `server/routers/knowledge.py` | 强制 RAG 重建 |
| `/api/policy/latest` | GET | `server/routers/policy.py` | 最新政策 |
| `/api/policy/summary` | GET | `server/routers/policy.py` | 政策摘要 |
| `/api/policy/sync` | POST | `server/routers/policy.py` | 触发政策爬取 |
| `/api/memory/short` | GET | `server/routers/memory.py` | 短期记忆 |
| `/api/memory/long` | GET | `server/routers/memory.py` | 长期记忆 |

---

## 五、Web界面

| 功能 | 代码位置 |
|------|---------|
| 聊天界面 | `web/index.html` |
| Onboarding引导 | `web/index.html` (JavaScript) |
| 标签页切换 | `web/index.html` |
| API Key设置 | `web/index.html` |
| 个性化指示器 | `web/index.html` |

---

## 六、测试文件

| 测试类型 | 文件 | 覆盖点 |
|---------|------|--------|
| 事件总线 + 反馈回流 | `tests/test_p3_integration.py` | EventBus / FEEDBACK_RECEIVED / KNOWLEDGE_UPDATED |
| Schema Registry | `tests/test_schema_registry.py` | 6 DB 初始化/幂等/元数据 |
| 短期记忆单例 | `tests/test_memory_singleton.py` | 双检锁、并发 |
| 响应映射 | `tests/test_response_mapper.py` | IntentType → response_type 覆盖 |
| 路由系统 | `tests/test_router_system.py` | 13 路由注册与分发 |
| 配置外部化 | `tests/test_config_externalization.py` | cities.yaml / sources.yaml 加载 |
| P1-余 Bug | `tests/test_p1_remaining.py` | planner 失败可见 + GraphRAG O(N) 去重 |
| 密钥安全 | `tests/test_secrets.py` | .env 占位符、.gitignore 命中 |
| 原有功能 | `tests/test_agent.py`, `tests/test_intent.py`, `tests/test_knowledge.py` | 意图/知识库 |
| **2026 计划补全** | `tests/test_memory_e2e.py` 等 9 个 | 见 P4-G |

---

## 七、修复记录

### P0–P3 重构期间修复(7 个 commit)

| Bug | 文件:行 | 修复内容 |
|-----|---------|---------|
| 4 个真实 API 密钥入库 | `.env` | 轮换为 `__SET_ME__` 占位符,`git-filter-repo` 清理历史 |
| `provider_key_map["minimax"]` | `src/main.py:553-577` | 改为正确大小写 `"MiniMax"` |
| onboarding 步骤分支重叠 | `src/agent/core.py:266` | `step >= len(questions) - 1`,显式 return |
| `_determine_response_type` 签名参数 | `src/agent/response.py:88-90` | 改为基于 `intent_type + entities` 计算 |
| `ShortTermMemory` 数据竞争 | `src/memory/short_term.py` | 双检锁单例,`get_short_term_memory()` 工厂 |
| `ThreadingHTTPServer` 缺失 | `src/main.py` | 改用 ThreadingHTTPServer 支持并发 |
| `Content-Length` 早返 413 缺失 | `src/main.py:222-228` | body 解析前 `int(headers.get('Content-Length',0)) > 2_000_000` |
| SQLite WAL 模式未启用 | `src/memory/long_term.py:117-132` 等 | 所有连接加 `PRAGMA journal_mode=WAL` + busy_timeout |
| `replace(day=32)` 月底溢出 | `src/knowledge/updater.py:760-787` | `calendar.monthrange(year, month)[1]` |
| `graphrag.py` 4 层 parent 路径错误 | `src/rag/graphrag.py:260-263` | 显式"根→子类→实体→实例" |
| `graphrag.py` 关系去重 O(N²) | `src/rag/graphrag.py:357` | `set` + frozenset 降到 O(N) |
| planner 失败任务静默 | `src/agent/planner/planner.py:168-174` | 记入 `failed_tasks`,返回结构化错误 |
| 城市/URL 硬编码 | `src/agent/graph/nodes.py:100` 等 | 外部化到 `config/cities.yaml` / `config/sources.yaml` |
| 知识库更新不触发 RAG | `src/knowledge/updater.py` | 完成后 `publish KNOWLEDGE_UPDATED` |
| 反馈不回流画像 | `src/feedback/feedback_manager.py` | 成功后 `publish FEEDBACK_RECEIVED` → `profile_subscriber` 消费 |
| main.py 1045 行巨石 | `src/main.py` | 拆为 `src/server/{routers,app}.py` 13 路由 |
| 6 个 SQLite DB schema 散落 | 各模块 `_init_database` | `src/db_schema.py` Schema Registry 统一管理 |

### 历史修复

| Bug | 文件 | 修复内容 |
|-----|------|---------|
| `build_chat_prompt` 参数名不匹配 | `src/agent/response.py` | 将 `personalization_ctx=` 改为 `user_profile=` |
| `rag_results` 变量作用域错误 | `src/agent/core.py` | 将变量定义移出if块，添加初始化 |
| `_calculate_engagement` sum字典值错误 | `src/agent/core.py` | 排除 `topic_interactions` 字典字段 |
| 大量调试日志写入文件 | `src/agent/response.py` | 删除所有 `debug-9b1c33.log` 写入代码 |
| Windows编码重复包装 | `src/agent/response.py` | 添加 `isinstance` 检查 |

---

*文档生成时间: 2026-04-16 | 最后更新: 2026-06-09*
