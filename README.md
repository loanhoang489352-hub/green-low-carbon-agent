# 绿色低碳智能体

基于消费者偏好建模的绿色智能体设计与实现

## 项目概述

这是一个可投入使用的绿色低碳智能体,核心解决"知行鸿沟"(从知道绿色低碳到行动起来)。具备以下核心能力:

- **垂类知识库**: 接入绿色低碳专业知识,支持 RAG 混合检索(语义+BM25)
- **三层记忆**: 会话/短期/长期,自动整合到长期,支持热度衰减与召回
- **用户画像图谱**: 节点+边关系,串起"用户→兴趣→行为→目标→成就→碳足迹"
- **行为阶段驱动**: 5 阶段(无意向→意向→准备→行动→维持)动态调整 LLM 策略
- **政策实时同步**: 每日定时爬取 + 事件触发 RAG 重建(2026 计划: P4-E)
- **个性化推荐**: 画像驱动 + RAG 命中 + 静态 ACTION_LIBRARY 混合
- **反馈回流**: 点赞/点踩自动沉淀到画像,影响后续推荐

## 系统架构

```
用户交互层(Web / API / CLI)
    ↓
智能体核心引擎 (意图理解 → 记忆召回 → 画像查询 → RAG 检索 → 响应生成)
    ↓
┌────────────┬────────────┬────────────┐
│  知识库系统 │  三层记忆   │ 画像图谱    │
│ (RAG)     │ (会话/短/长) │ (节点+边)  │
└────────────┴────────────┴────────────┘
    ↓
事件总线(KNOWLEDGE_UPDATED / FEEDBACK_RECEIVED)
    ↓
数据存储层(6 个 SQLite + ChromaDB)
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 运行智能体

**Web 界面模式(推荐)**:
```bash
cd src
python main.py
```
然后在浏览器打开 http://localhost:8000

**命令行模式**:
```bash
cd src
python main.py --cli
```

**LangGraph 模式**:
```bash
cd src
python main.py --use-langgraph --use-react
```

### 3. 运行测试

```bash
pytest tests/ -v
```

## 目录结构

```
绿色低碳智能体/
├── SPEC.md                    # 系统设计规范
├── README.md                  # 项目说明(本文件)
├── CLAUDE.md                  # Claude Code 上下文
├── CODE_MAPPING.md            # SPEC 章节 ↔ 代码文件映射
├── requirements.txt           # Python 依赖
├── .env.example               # 环境变量模板(占位符)
├── config/
│   ├── settings.yaml          # 全局配置
│   ├── cities.yaml            # 城市配置(P2-余 外部化)
│   └── sources.yaml           # 政策源 URL(P2-余 外部化)
├── src/
│   ├── main.py                # 入口(委托给 server.app)
│   ├── paths.py               # 统一路径
│   ├── config.py              # Pydantic Settings
│   ├── config_loader.py       # YAML 加载
│   ├── db_schema.py           # Schema Registry(6 DB)
│   ├── events.py              # 事件总线
│   ├── server/                # HTTP 服务(13 路由)
│   │   ├── app.py
│   │   ├── router.py
│   │   ├── errors.py
│   │   └── routers/           # 8 个路由文件
│   ├── agent/
│   │   ├── core.py            # GreenAgent
│   │   ├── langgraph_agent.py # LangGraphAgent
│   │   ├── response.py        # 响应生成
│   │   ├── response_mapper.py # IntentType → response_type
│   │   ├── intent.py          # 意图识别
│   │   ├── memory/            # 三层记忆
│   │   ├── knowledge/         # 知识库
│   │   ├── rag/               # RAG + GraphRAG
│   │   ├── user_profile/      # 画像 + 行为追踪 + 推荐
│   │   ├── policy/            # 政策更新
│   │   ├── tools/             # 工具抽象
│   │   ├── planner/           # 任务规划
│   │   └── graph/             # LangGraph 工作流
│   ├── feedback/              # 反馈 + 画像订阅
│   └── auth/                  # 账户管理
├── knowledge_base/            # 知识库文件
│   ├── basic/                # 基础知识
│   ├── policy/               # 政策(2026 计划按地区切分)
│   └── guide/                # 实操指南
├── web/
│   └── index.html            # Web 界面
├── scripts/                   # 一次性脚本
└── tests/                     # pytest 测试
    ├── conftest.py
    ├── test_p3_integration.py # 事件总线 + 反馈回流
    ├── test_schema_registry.py # Schema 6 DB
    ├── test_memory_singleton.py
    ├── test_response_mapper.py
    ├── test_p1_remaining.py
    ├── test_config_externalization.py
    ├── test_router_system.py
    └── test_secrets.py
```

## 核心模块说明

### 1. 意图识别(`src/agent/intent.py`)

基于规则的轻量级意图识别:
- 知识查询 (KNOWLEDGE_QUERY)
- 建议请求 (ADVICE_REQUEST)
- 行动报告 (ACTION_REPORT)
- 反馈 (FEEDBACK)
- 问候 (GREETING)
- 其他 (OTHER)

### 2. 知识库(`src/knowledge/`, `src/rag/`)

- Markdown 文档 `knowledge_base/` (basic/policy/guide)
- RAG 引擎:语义(ChromaDB)+ BM25 关键词,混合检索
- GraphRAG:实体/关系提取,多跳推理
- 增量更新:外部政策源变化时 publish KNOWLEDGE_UPDATED → RAG 重建
- 元数据过滤:按地区、领域筛选(2026 计划: P4-F)

### 3. 三层记忆(`src/agent/memory/`)

- **会话/上下文**(`ConversationContext`):per-user,内存,带 TTL
- **短期**(`ShortTermMemory`):单例,conversations dict,7 天 TTL,工作记忆最近 5 轮
- **长期**(`LongTermMemory`):SQLite + WAL,user_memories + user_preferences 两表
- **整合**(`MemoryConsolidator`):轮次≥10 / 空闲≥2h / 重要性≥0.6 触发

### 4. 用户画像(`src/user_profile/`)

- **画像图谱**(`profile_graph.py`):User ↔ Interest ↔ Action ↔ Goal ↔ Achievement ↔ CarbonFootprint
- **行为阶段**(`behavior_stage`):无意向→意向→准备→行动→维持(TTM 5 阶段)
- **个性化推荐**(`personalized_recommender.py`):静态库 + RAG 命中 + 画像过滤
- **持久化**:`profile_data` JSON,`user_goals` / `user_achievements` / `carbon_footprint_log` 表

### 5. 政策更新(`src/policy/`)

- 政策数据库(`data/policy_updates.db`)
- 外部源:`config/sources.yaml` 列出生态环境部、发改委等
- 2026 计划:实现 httpx+BS4 真实爬取(目前是 stub)

## API 接口

服务启动后可访问 http://localhost:8000/ 查看 Web 界面,API 文档参见 CLAUDE.md。

| 接口类别 | 端点 |
|---------|------|
| 系统 | `/api/health` |
| 对话 | `/api/chat`, `/api/chat/enhanced` |
| 认证 | `/api/auth/{register,login,logout}` |
| 画像 | `/api/profile` (GET/PUT) |
| 引导 | `/api/onboarding/{start,answer,status}` |
| 反馈 | `/api/feedback` |
| 知识库 | `/api/knowledge/{stats,query,reload}` |
| 政策 | `/api/policy/{latest,summary,sync}` |
| 记忆 | `/api/memory/{short,long}` |

## 扩展建议

### 接入大语言模型

修改 `config/settings.yaml` 中的 LLM 配置:

```yaml
llm:
  provider: "deepseek"  # 或 openai / MiniMax
  model: "deepseek-chat"
  api_key: "${DEEPSEEK_API_KEY}"
```

`.env` 中填入真实 API 密钥(`__SET_ME__` 占位符替换)。

### 添加更多知识

在 `knowledge_base/` 对应目录下添加 Markdown 文件,然后:
```bash
curl -X POST http://localhost:8000/api/knowledge/reload
```
触发 RAG 重建。

## 毕设相关

本项目是为本科毕业设计"基于消费者偏好建模的绿色智能体设计与实现"开发的演进版。

### 设计要点

1. **三层记忆**:会话/短期/长期,自动整合 → 积累"知道"
2. **画像图谱**:节点+边关系,支持图谱推理 → 实现"个性化"
3. **行为阶段驱动**:5 阶段策略,差异化 LLM 回复 → 推动"行动"
4. **事件总线**:知识更新/反馈自动回流,降低耦合
5. **Schema Registry**:6 DB 集中管理,切换 Alembic 成本低

### 已知限制与未来工作

详见 `~/.claude/plans/bug-agent-groovy-flute.md` 与 `docs/refactor-plan-v2.md`(2026 计划):
- P4-A:启动时事件订阅 + APScheduler 调度 + LangGraph Checkpointer
- P4-B:三层记忆真正打通(consolidation 接入、节点写短记、热度衰减、记忆召回)
- P4-C:画像图谱接入 UserProfileManager,Goal/Achievement/CarbonFootprint 持久化
- P4-D:行为阶段真正驱动 LLM(差异化 system prompt)
- P4-E:政策 httpx+BS4 实爬,RAG 真正自动重载
- P4-F:知识库按地区/兴趣个性化
- P4-G:9 个端到端测试补全

## 许可证

MIT License
