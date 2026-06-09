# 绿色低碳智能体

基于消费者偏好建模的绿色智能体设计与实现

## 项目概述

这是一个可投入使用的绿色低碳智能体,核心解决"知行鸿沟"(从知道绿色低碳到行动起来)。具备以下核心能力:

- **垂类知识库**: 接入绿色低碳专业知识,支持 RAG 混合检索(语义+BM25)
- **三层记忆(P4-H)**: 短期(单 session) + 工作(per-user 跨 session, workspace 命名空间) + 长期(永久);级联召回短→工作→长,OpenClaw 风格 heartbeat 审计
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
│   │   ├── memory/            # 三层记忆(短+工作+长,P4-H)
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

### 3. 三层记忆(`src/memory/`)— P4-H 工作记忆补齐

- **短期**(`ShortTermMemory`):单例,conversations dict,7 天 TTL,5 轮滑动窗口 + 旧轮次摘要
- **工作**(`WorkingMemory`, P4-H):per-user 跨 session workspace 命名空间
  - 命名空间 set/get/delete,同名 key 覆盖检测(防任务污染)
  - 容量上限 50 key(LRU 淘汰)+ 24h TTL(过期清理)
  - JSON 快照持久化(跨重启) + heartbeat 每 4h 审计
  - OpenClaw 风格:Agent 自由写,heartbeat 整理
- **长期**(`LongTermMemory`):SQLite + WAL,user_memories + user_preferences 两表,半衰期 30 天衰减
- **整合**(`MemoryConsolidator`):轮次≥10 / 空闲≥2h / 重要性≥0.6 触发
  - P4-H 新增 短→工作 晋升(`_promote_to_working`)
  - P4-H 新增 heartbeat 工作→长 晋升(importance ≥ 0.7)
- **级联召回**(`memory_agent.py`, P4-H):`cascaded_recall(user_id, query, conv_id)`
  - should_recall 扫信号词("上次/之前/那个/继续")
  - 短→工作→长 级联(能用免费的就用免费的,类比缓存→数据库)

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

1. **三层记忆(P4-H)**:短期(对话) + 工作(per-user workspace) + 长期(永久);级联召回短→工作→长,OpenClaw 风格 heartbeat 审计 → 积累"知道"+ "任务状态"
2. **画像图谱**:节点+边关系,支持图谱推理 → 实现"个性化"
3. **行为阶段驱动**:5 阶段策略,差异化 LLM 回复 → 推动"行动"
4. **三层记忆(P4-H)**:工作记忆(per-user workspace)+ 级联召回(短→工作→长)+ heartbeat 审计
5. **事件总线**:知识更新/反馈自动回流,降低耦合
6. **Schema Registry**:6 DB 集中管理,切换 Alembic 成本低

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
