# 代码与开题报告对应关系

本文档建立 SPEC.md 章节与核心代码模块的映射，方便论文答辩时快速定位实现位置。

---

## 一、系统架构（SPEC.md 第1-2章）

| SPEC 章节 | 实现位置 | 说明 |
|-----------|---------|------|
| 技术架构概览 | `src/main.py` | HTTP服务器入口，路由分发 |
| 核心引擎 | `src/agent/core.py` | `GreenAgent` 类，整合所有模块 |
| 意图理解 | `src/agent/intent.py` | `IntentRecognizer` 类 |
| 响应生成 | `src/agent/response.py` | `ResponseGenerator` 类 |
| LangGraph架构 | `src/agent/langgraph_agent.py` | 预留扩展接口 |

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
| 政策更新器 | `src/policy/updater.py` | `PolicyUpdater` 类 |
| 政策数据库 | 内存存储 | `get_latest_policies()` 方法 |
| 政策摘要 | `src/policy/updater.py` | `generate_policy_summary()` 方法 |

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
| `/api/chat` | POST | `main.py` | 基础对话 |
| `/api/chat/enhanced` | POST | `main.py` | 增强对话(RAG+个性化) |
| `/api/user/register` | POST | `main.py` | 用户注册 |
| `/api/user/update` | POST | `main.py` | 更新画像 |
| `/api/profile/{user_id}` | GET | `main.py` | 获取画像 |
| `/api/personalization/{user_id}` | GET | `main.py` | 获取个性化上下文 |
| `/api/stats/{user_id}` | GET | `main.py` | 用户统计 |
| `/api/knowledge/stats` | GET | `main.py` | 知识库统计 |
| `/api/rag/stats` | GET | `main.py` | RAG统计 |
| `/api/policy/latest` | GET | `main.py` | 最新政策 |
| `/api/policy/summary` | GET | `main.py` | 政策摘要 |
| `/api/onboarding/status` | POST | `main.py` | 引导状态 |
| `/api/onboarding/start` | POST | `main.py` | 开始引导 |
| `/api/onboarding/answer` | POST | `main.py` | 回答引导问题 |
| `/api/onboarding/questions` | GET | `main.py` | 引导问题列表 |
| `/api/health` | GET | `main.py` | 健康检查 |

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

| 测试类型 | 文件 |
|---------|------|
| 核心修复验证 | `verify_fixes.py` |
| 全面功能测试 | `test_comprehensive.py` |
| 单元测试 | `tests/test_unit.py` |
| 原有的测试 | `tests/test_agent.py` |

---

## 七、修复记录

本次开发计划中修复的Bug：

| Bug | 文件 | 修复内容 |
|-----|------|---------|
| `build_chat_prompt` 参数名不匹配 | `src/agent/response.py` | 将 `personalization_ctx=` 改为 `user_profile=` |
| `rag_results` 变量作用域错误 | `src/agent/core.py` | 将变量定义移出if块，添加初始化 |
| `_calculate_engagement` sum字典值错误 | `src/agent/core.py` | 排除 `topic_interactions` 字典字段 |
| 大量调试日志写入文件 | `src/agent/response.py` | 删除所有 `debug-9b1c33.log` 写入代码 |
| Windows编码重复包装 | `src/agent/response.py` | 添加 `isinstance` 检查 |

---

*文档生成时间：2026-04-16*
