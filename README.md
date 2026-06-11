# 🌱 绿色低碳智能体(Green Low-Carbon Agent)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Version 2.1.0](https://img.shields.io/badge/version-2.1.0-green.svg)](./CHANGELOG.md)
[![Tests: 254+](https://img.shields.io/badge/tests-254%2B-brightgreen.svg)](./tests/)

> 基于消费者偏好建模的**个性化低碳生活助手**,解决"知行鸿沟"
> (从知道绿色低碳到行动起来)。
> **可上线 · MIT License · 39 commit · 5 维度全 5★**

---

## ✨ 核心能力

- 🧠 **三层记忆** — 短期(会话) + 工作(per-user 跨会话 workspace) + 长期(永久),OpenClaw 风格 heartbeat 审计
- 👤 **用户画像图谱** — User ↔ Interest ↔ Action ↔ Goal ↔ Achievement ↔ CarbonFootprint,节点+边关系
- 📚 **RAG 知识库** — 150+ 文档块,ChromaDB 向量检索 + BM25 关键词 + GraphRAG 多跳推理
- 🎯 **行为阶段驱动** — 5 阶段(无意向→意向→准备→行动→维持)动态调整 LLM 策略
- 💬 **个性化推荐** — 画像驱动 + RAG 命中 + 静态 ACTION_LIBRARY 混合
- 🌍 **政策实时同步** — 17 个源(政府/媒体/国际)每日 02:00 自动爬取
- 🔒 **完整鉴权** — Bearer session_id + bcrypt 密码 + 60 req/60s 限流 + 审计日志 + PII 脱敏
- 🌐 **中英双语** — API 错误消息 + Web UI 浮动切换器,跟随 Accept-Language
- 💾 **灾备脚本** — 全量/增量 tar.gz + SHA256 + 自动清理 + S3 上传可选
- 🐳 **Docker 部署** — multi-stage + 健康检查 + non-root + graceful shutdown
- 📊 **可观测性** — trace_id + JSON 日志 + /api/metrics + /api/health/ready

---

## 🚀 快速开始

### 1. 克隆与安装

```bash
git clone https://github.com/loanhoang489352-hub/green-low-carbon-agent.git
cd green-low-carbon-agent
pip install -r requirements.txt
pip install -r requirements-dev.txt  # 开发依赖
```

### 2. 配置环境变量

```bash
cp .env.example .env
vim .env
# 填入真实 API key(或设 LLM_MOCK=true 用 mock 模式)
```

### 3. 启动 Web 服务

```bash
cd src && python main.py
# 打开 http://localhost:8000/
```

### 4. 验证健康

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
curl http://localhost:8000/api/metrics
```

### 5. Docker 部署(生产)

```bash
make prod    # 启动生产容器(读 .env.prod)
```

详见 `deploy/` 目录(systemd / nssm / nginx / RUNBOOK)。

---

## 🏗️ 系统架构

```
                    ┌──────────────────────────┐
                    │     用户交互层            │
                    │  Web UI / REST API / CLI  │
                    │  中英双语(浮动切换器)    │
                    └──────────────────────────┘
                                ↓
┌───────────────────────────────────────────────────────────┐
│                 智能体核心引擎(agent/)                    │
│  意图识别 → 记忆召回 → 画像查询 → RAG 检索 → 响应生成   │
│  行为阶段 → 个性化推荐 → Query Cache(30%+ LLM 降本)    │
│  LangGraph 6 节点工作流 + WorkingMemory heartbeat         │
└───────────────────────────────────────────────────────────┘
                                ↓
┌──────────────┬──────────────────┬──────────────────────┐
│  知识库系统  │   三层记忆        │  用户画像图谱        │
│  (RAG)       │  (memory/)        │  (user_profile/)      │
│              │                   │                       │
│ ChromaDB     │  ShortTerm       │  User ↔ Interest      │
│ + BM25       │  + Working       │  ↔ Action ↔ Goal     │
│ + GraphRAG   │  + LongTerm      │  ↔ Achievement       │
│ 157 文档块   │  级联召回        │  ↔ CarbonFootprint   │
└──────────────┴──────────────────┴──────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────┐
│              数据存储 + 基础设施层                        │
│  7 SQLite(账号/画像/反馈/政策/短/长/行为) + ChromaDB  │
│  + Query Cache + WorkingMemory JSON 快照 + 审计日志     │
│  SQLite 连接池(12.5x 提升)+ WAL + busy_timeout         │
└─────────────────────────────────────────────────────────┘
                ↓
┌─────────────────────────────────────────────────────────┐
│         事件总线 + 调度 + 可观测性                        │
│  KNOWLEDGE_UPDATED / FEEDBACK_RECEIVED / PROFILE_UPDATED│
│  APScheduler(每日 02:00 KB 更新 / 03:00 记忆衰减)       │
│  trace_id 贯穿 / JSON 日志 / /api/metrics                │
└─────────────────────────────────────────────────────────┘
```

---

## 📦 功能详解

### 1. 三层记忆(`src/memory/`)— P4-H + P5-G + P6.E.2

| 层 | 文件 | 范围 | 容量 | 持久化 |
|---|---|---|---|---|
| 短期 | `short_term.py` | 单 session | 5 轮 + 摘要 | SQLite(P5-G) + 池化(P6.E.2) |
| 工作 | `working.py` | per-user 跨 session | 50 key LRU + 24h TTL | JSON 快照 + heartbeat(P6.D 修复) |
| 长期 | `long_term.py` | 全局 | 索引 < 40 行 + 30 天半衰期 | SQLite + embedding BLOB + 向量检索 |

**级联召回**:`memory_agent.py` 扫信号词("上次/之前/那个")→ 短→工作→长 级联,能用免费的就用免费的(类比缓存→数据库)。

### 2. 用户画像图谱(`src/user_profile/`)— P4-C

- **节点**:User / Interest / Action / Goal / Achievement / CarbonFootprint
- **边**:`has_interest` / `performs_action` / `has_goal` / `earned_achievement` / `reduces_carbon`
- **持久化**:`user_profiles.db` JSON 字段 + `behavior_tracker.db` 4 张表
- **图谱推理**:BFS/DFS 找高置信度路径,生成"为什么推荐这个"的解释

### 3. RAG 知识库(`src/rag/` + `src/knowledge/`)— P5-H + P6.J

- **ChromaDB** Windows 持久化 + 异步重建 + 进度查询
- **混合检索** 向量 + BM25 + 软重排(画像 region/interests 加权)
- **GraphRAG** 实体/关系提取 + 多跳推理
- **157 文档块** 来自 17 个源(政府权威 + 媒体 + 国际研究)
- **自动评估** `tests/eval/golden_set.jsonl` 50 条 + hit_rate@5 / MRR@10 / NDCG@10

### 4. 政策更新(`src/policy/`)— P4-E + P6.J

- `config/sources.yaml` 17 源,每日 02:00 自动检查
- 港 IP 实测 7 新源启用(新华网 / 经济参考报 / 财新 / 南方周末 / 国家发改委 / 国家统计局 / EDF)
- 工具脚本 `scripts/test_new_sources.py` 自动测试 + 报告

### 5. LangGraph 工作流(`src/agent/graph/`)

6 节点:`recognize_intent` → `recall_memories` → `retrieve_knowledge` → `update_profile` → `generate_recommendations` → `generate_response`
- 软过滤(画像 region/interests)
- 画像回写(每轮更新图谱)
- P5-A SqliteSaver checkpointer(跨 session 持久化)

### 6. LLM 集成(`src/llm/`)— P5-A/C/G/I

- 6 provider:OpenAI / Zhipu / Baidu / Ali / MiniMax / DeepSeek
- Bayesian 路由器自动选 provider
- `LLMResponse` 统一契约(content / latency_ms / request_id / usage / error)
- `LLM_MOCK=true` 强制 mock,测试/开发不依赖真实 API
- `OpenAIClient.achat()` async 版本(httpx.AsyncClient)

---

## 📊 关键性能数字

| 指标 | 数字 | 备注 |
|---|---|---|
| Server 端 in-process 吞吐 | **109,603 req/s** | 50 线程并发 / 1000 次 health 探测 |
| SQLite 连接池吞吐 | **20,223 req/s** | 12.5x 提升(基线 1,623) |
| Query Cache 命中延迟 | **< 10ms** | vs LLM 真实 1-3s |
| 限流触发 | **第 59 次** | 60 req/60s/IP |
| SIGTERM 优雅退出 | **5s 内** | 等待 inflight ≤ 10s |
| 知识库文档 | **157 块** | KB-v2 → v7 + P6.J 7 源 |
| 源覆盖 | **17 源** | 政府 + 媒体 + 国际 |
| LLM 调用成本节省 | **30%+** | Query Cache 命中率 |
| 测试数 | **254+** | P0-P3 基础 + P4 65 + P5 50 + P6 124 |
| 5 维度成熟度 | **全 5★** | 功能 / 性能 / 观测 / 安全 / 部署 |

---

## 🌐 API 端点(35+)

详见 `docs/API.md` 或 `CLAUDE.md` 的"API 端点"章节。

| 类别 | 端点 | 说明 |
|---|---|---|
| 系统 | `/api/health` `/api/ready` `/api/metrics` | 健康 + K8s readiness + LLM 指标 + Query Cache |
| 鉴权 | `/api/auth/{register,login,logout,check,session}` | Bearer session_id(P6.A 全部路由已落地) |
| 对话 | `/api/chat` `/api/chat/enhanced` | 基础 + RAG 个性化(需鉴权) |
| 画像 | `/api/profile/{user_id}` | 增删改查(需鉴权) |
| 引导 | `/api/onboarding/{start,answer,status}` | 8 步问卷 |
| 反馈 | `/api/feedback*` | 点赞/点踩/评论(需鉴权) |
| 知识库 | `/api/knowledge/{stats,query,reload}` | 检索 + 强制重建 |
| 政策 | `/api/policy/{latest,summary,sync}` | 17 源自动同步 |
| 记忆 | `/api/memory/{short,long}` | 三层记忆查询 |
| Web | `/` `/i18n.js` | Web UI + 前端 i18n |

---

## 🚀 部署

### Docker(推荐)

```bash
make prod    # 读 .env.prod 启动生产容器
make prod-status  # 探活
make prod-logs    # 跟踪日志
make backup       # 灾备(P6.F)
```

详见 `Dockerfile`(multi-stage,non-root)+ `docker-compose.yml`(资源限制 / 日志 100MB / 限流)+ `deploy/RUNBOOK.md`。

### 本地开发

```bash
cd src && python main.py    # 默认 :8000
```

### systemd / nssm

`deploy/green-agent.service`(Linux)+ `deploy/nssm-install.ps1`(Windows)。

---

## 📚 文档导航

- 📖 **[CLAUDE.md](./CLAUDE.md)** — Claude Code 协作指南(架构/命令/模块说明)
- 📋 **[CHANGELOG.md](./CHANGELOG.md)** — 完整版本演进(P0 → v2.1.0,39 commit)
- 🔒 **[docs/SECURITY.md](./docs/SECURITY.md)** — PII / 密码 / 限流 / 审计 / 依赖管理
- 🛠 **[docs/RUNBOOK.md](./docs/RUNBOOK.md)** — 4 故障场景运维手册
- 🌐 **[docs/API.md](./docs/API.md)** — 35+ API 端点文档
- 🤝 **[CONTRIBUTING.md](./CONTRIBUTING.md)** — 贡献指南(9 章节)
- 📜 **[LICENSE](./LICENSE)** — MIT 许可证
- ⚖️ **[THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)** — 第三方依赖许可证汇总
- 🔍 **[docs/P6J_GOV_SOURCES.md](./docs/P6J_GOV_SOURCES.md)** — 拓源流程

---

## 🧪 跑测试

```bash
# 全量(254+ 测试,~30s)
pytest tests/ -v --tb=short

# 端到端(P4G / P6D)
pytest tests/test_p4g_e2e.py tests/test_p6d_full_chain.py -v

# 单元 + mock(无网络)
LLM_MOCK=true pytest tests/ -v

# 知识库质量评估
python scripts/eval_retrieval.py --subset curated

# 项目健康自检(5/5 应过)
python scripts/doctor.py
```

---

## 🎯 路线图(已完成)

| 阶段 | 状态 | 关键产出 |
|---|---|---|
| **P0–P3** | ✅ | 基础架构 / 事件总线 / Schema Registry |
| **P4-A~H** | ✅ | 三层记忆 / 画像图谱 / RAG / 行为阶段 / 政策爬取 / 个性化 |
| **P5-A~I** | ✅ | LLM 契约 / 可观测性 / 可靠性 / 鉴权 / 错误处理 / 日志 / 评估 / 持久化 / 安全合规 |
| **P5-J** | ✅ | 部署资产(Docker / systemd / nssm / nginx / RUNBOOK) |
| **P6 全 14 方向** | ✅ | 鉴权真落地 / 健康缓存 / Query Cache / 全链路 / SQLite 池 / 灾备 / LLM_MOCK / i18n / async LLM / 拓源 / LICENSE / Web i18n / CONTRIBUTING / CHANGELOG |

---

## 🙏 致谢

- [LangGraph](https://github.com/langchain-ai/langgraph) — 状态机工作流
- [ChromaDB](https://github.com/chroma-core/chroma) — 向量数据库
- [sentence-transformers](https://github.com/UKPLab/sentence-transformers) — 多语言嵌入
- [APScheduler](https://github.com/agronholm/apscheduler) — 任务调度
- [Pydantic](https://github.com/pydantic/pydantic) — 数据验证
- 全部依赖见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)

---

## 📜 许可证

本项目采用 [MIT License](./LICENSE)。

```
Copyright (c) 2026 绿色低碳智能体项目组
允许商业使用、修改、分发、私有 fork,只需保留版权声明。
```

---

**绿色低碳智能体** — 让"知道"成为"行动" 🌱♻️⚡
