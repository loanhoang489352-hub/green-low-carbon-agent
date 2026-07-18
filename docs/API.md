# API 文档

绿色低碳智能体的 HTTP API(基于 `http.server.ThreadingHTTPServer`,P1 起)路由表与契约。
所有路由通过 `src/server/routers/` 模块注册,统一在 `app.py: _dispatch()` 分发,
鉴权(P5-D)、限流(P5-I.B)、审计(P5-I.B)三件套在分发链路上自动应用。

## 通用约定

- **Base URL**: `http://<host>:<port>`(默认 `http://127.0.0.1:8000`)
- **鉴权**:除 `auth/register|login`、`/`、`/api/health`、`/api/ready`、`/api/metrics`、
  `/api/rag/stats` 之外,**所有端点都需要 `Authorization: Bearer <session_id>` 头或
  `X-Session-Id: <session_id>` 头**(P5-D,P5-I.B 审计)
- **限流**:默认 60 req / 60s / IP(可由 `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW` 调),
  超限返 `429 RATE_LIMITED` 含 `retry_after` 字段(P5-I.B)
- **错误格式**:所有非 2xx 响应均为 JSON:
  ```json
  {"code": "UNAUTHORIZED", "message": "Invalid or missing session token", "status": 401}
  ```
- **请求体**:POST 请求 Content-Type 须为 `application/json`;`max_body_size=2 MB`
- **响应体**:统一 JSON,UTF-8 编码,`Content-Type: application/json; charset=utf-8`
- **CORS**:`Access-Control-Allow-Origin` 由 `CORS_ORIGINS` 决定(逗号分隔)

## 系统

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/` | GET | ❌ | Web 入口(返回 `web/index.html`) |
| `/api/health` | GET | ❌ | 真探活(P5-E):DB / Chroma / Scheduler / 延迟,503 表示 down |
| `/api/ready` | GET | ❌ | K8s readiness(轻量级,只查 accounts.db) |
| `/api/metrics` | GET | ❌ | LLM 调用聚合(P50/P95 延迟 + token 用量 + 错误率) |

### GET /api/health
```json
{
  "ok": true,
  "service": "绿色低碳智能体",
  "version": "2.0",
  "langgraph": false,
  "health": {
    "status": "ok",          // ok / degraded / down
    "checks": {
      "accounts_db": {"ok": true},
      "user_profiles_db": {"ok": true},
      "vector_store": {"ok": true, "persistent": true, "count": 67},
      "scheduler": {"ok": true, "running": true, "jobs": 5},
      "metrics": {"ok": true, "last_latency_ms": 1230},
      "disk": {"ok": true, "free_gb": 12.3}
    }
  }
}
```

## 认证(Auth)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/auth/register` | POST | ❌ | 注册新账号 |
| `/api/auth/login` | POST | ❌ | 登录获取 session_id |
| `/api/auth/logout` | POST | ✅ | 销毁 session |

### POST /api/auth/register
请求:
```json
{"username": "alice", "password": "supersecret"}
```
响应:
```json
{"success": true, "account_id": "abc123", "username": "alice"}
```

### POST /api/auth/login
请求:同 register
响应:
```json
{
  "success": true,
  "session_id": "uuid-xxx",
  "account_id": "abc123",
  "username": "alice",
  "expires_at": "2026-06-17T..."
}
```
session_id 默认 7 天有效。

## 聊天(Chat)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/chat` | POST | ✅ | 基础聊天 |
| `/api/chat/enhanced` | POST | ✅ | 增强聊天(RAG + 画像 + 记忆) |

### POST /api/chat/enhanced
请求:
```json
{
  "message": "北京的低碳政策有哪些?",
  "session_id": "uuid-xxx",
  "user_id": "user-1",     // 可选,缺省 = session 关联的 user
  "location": {            // P6.S.22 可选,前端浏览器定位回调
    "lat": 39.9042,
    "lng": 116.4074,
    "city": "北京",
    "region": "北京市",
    "country": "中国"
  }
}
```
响应:
```json
{
  "ok": true,
  "message": "...",
  "intent": "KNOWLEDGE_QUERY",         // P6.S.23 新增 LOCATION_QUERY
  "suggestions": [...],
  "knowledge_refs": [{"source": "policy/...", "score": 0.87}],
  "tool_result": {                     // P6.S.23 新增: 出行/天气/路线等工具调用结果
    "origin": "北京西站",
    "destination": "首都机场",
    "routes": [
      {"type": "公交", "distance_km": 32.5, "duration_min": 65,
       "carbon_kg": 0.3, "cost_yuan": 7.0, "polyline": [{"lat":39.89,"lng":116.32}, ...]}
    ],
    "weather": {"temp": 22, "desc": "晴"},
    "recommended": {...}
  },
  "recommendations": [...],
  "location": {                        // P6.S.22 定位来源(browser / ip / profile)
    "city": "北京",
    "region": "北京市",
    "country": "中国",
    "source": "browser",
    "lat": 39.9042,
    "lng": 116.4074
  },
  "personalization": {...},
  "profile_updates": {...},
  "timestamp": "2026-06-15T...",
  "conversation_id": "conv-xxx"
}
```

> **P6.S.23 变更**:
> - `tool_result` 字段此前漏返,前端无法消费;现已补全,出行/天气/路线/碳排对比等工具调用结果全部透出
> - `intent` 新增 `LOCATION_QUERY`(用户在问"我的位置 / where am i"),响应中 `message` 直接包含 "📍 你在 北京 · 浏览器定位"
> - `location` 是 best_location() 3 层 fallback 结果,前端可在助手消息右上角显示标签

## 画像(Profile)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/profile` | GET | ✅ | 获取用户画像 |
| `/api/profile` | PUT | ✅ | 更新画像字段 |

### GET /api/profile
```json
{
  "user_id": "user-1",
  "basic_info": {"age_range": "25-34", "region": "beijing"},
  "eco_profile": {"interests": ["low_carbon_travel"], "stage": "action"},
  "graph": {...},   // 画像图谱 JSON(P4-C)
  "onboarding_completed": true
}
```

## 引导(Onboarding)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/onboarding/start` | POST | ✅ | 开始 8 步问卷 |
| `/api/onboarding/answer` | POST | ✅ | 回答单步问题 |
| `/api/onboarding/status` | GET | ✅ | 查进度 |

## 反馈(Feedback)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/feedback` | POST | ✅ | 提交反馈(like / dislike / comment) |

### POST /api/feedback
请求:
```json
{
  "message_id": "msg-xxx",
  "feedback_type": "comment",   // like | dislike | comment
  "comment": "回答很专业",         // P5-I.A: 自动脱敏 PII
  "reason": null,                // dislike 时必填
  "session_id": "uuid-xxx"
}
```

## 记忆(Memory)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/memory/short` | GET | ✅ | 短期记忆(STM) |
| `/api/memory/long` | GET | ✅ | 长期记忆(LTM) |

## 知识库(Knowledge)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/knowledge/stats` | GET | ❌ | 知识库统计 |
| `/api/knowledge/query` | POST | ✅ | 知识库查询(走 RAGEngine) |
| `/api/knowledge/reload` | POST | ✅ | 触发异步重建(P5-H.C) |

### GET /api/knowledge/stats
```json
{
  "total_documents": 300,            // P6.S.23: 优先 RAG vector_store_count + bm25_doc_count
  "knowledge_base_files": 68,        // P6.S.23: 静态 markdown 文件数(供前端副标题)
  "categories": {"basic": 10, "policy": 30, "guide": 8, "regional": 12},
  "rag_enabled": true,
  "rag_stats": {
    "vector_store_count": 150,
    "bm25_doc_count": 150,
    "is_enabled": true,
    "config": {...}
  }
}
```

> **P6.S.23 变更**:`total_documents` 之前是 `KnowledgeManager.documents` 的内存长度(可能 0),
> 现优先用 RAG 实际块数(150)。`knowledge_base_files` 保留静态 KB 文件数,前端副标题展示。

## RAG

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/rag/stats` | GET | ❌ | RAG 引擎状态 |
| `/api/rag/status` | GET | ❌ | 异步重建进度(P5-H.C) |

### GET /api/rag/status
```json
{
  "state": "done",            // idle / running / done / error
  "progress": 100,
  "total": 67,
  "message": "indexed 67 documents"
}
```

## 政策(Policy)

| 端点 | 方法 | 鉴权 | 说明 |
|---|---|---|---|
| `/api/policy/latest` | GET | ❌ | 最新 10 条政策 |
| `/api/policy/summary` | GET | ❌ | 政策摘要统计 |
| `/api/policy/sync` | POST | ✅ | 触发实爬(P4-E) |

## 错误码

| code | HTTP | 含义 |
|---|---|---|
| `UNAUTHORIZED` | 401 | 无 / 过期 / 错 session token |
| `NOT_FOUND` | 404 | 路由不存在 |
| `BAD_REQUEST` | 400 | JSON 解析失败 / 参数缺失 |
| `BODY_TOO_LARGE` | 413 | body 超过 2MB |
| `RATE_LIMITED` | 429 | IP 限流(响应含 `retry_after`) |
| `INTERNAL` | 500 | 兜底:不向客户端泄栈,仅记 error.log |

## 审计(P5-I.B)

下列端点会写 `accounts.db.audit_log` 表:

- `POST /api/auth/login`(成功 + 失败)
- `POST /api/auth/register` / `logout`
- `POST /api/chat/enhanced`
- `POST /api/feedback`
- `PUT /api/profile`
- `POST /api/onboarding/*`
- `POST /api/policy/sync`
- `POST /api/knowledge/reload`
- 401 鉴权失败 + 429 限流 也各记一条

字段:`id / user_id / action / target / ip / user_agent / status_code / detail / created_at`。
`detail` 字段自动过 PII 脱敏(避免二次泄露)。

## 指标(P5-B + P6.C)

### GET /api/metrics
```json
{
  "ok": true,
  "service": "绿色低碳智能体",
  "metrics": {
    "total_calls": 42,
    "error_rate": 0.024,
    "avg_latency_ms": 1230,
    "p50_latency_ms": 980,
    "p95_latency_ms": 2400,
    "p99_latency_ms": 4100,
    "total_tokens": 124567,
    "by_provider": {
      "openai": {"calls": 30, "error_rate": 0.0, "tokens": 80000},
      "deepseek": {"calls": 12, "error_rate": 0.083, "tokens": 44567}
    },
    "history_size": 1000,
    "query_cache": {
      "hits": 1234,
      "misses": 56,
      "sets": 567,
      "invalidations": 12,
      "hit_rate": 0.957,
      "size": 234,
      "ttl_seconds": 3600
    }
  }
}
```

**Query Cache 字段**(P6.C):
- `hits` — LLM 缓存命中次数(命中后跳过真实 API 调用)
- `misses` — 未命中次数
- `sets` — 写入次数
- `invalidations` — 画像更新触发的清除条数
- `hit_rate` — 命中率(`hits / (hits + misses)`)
- `size` — 当前缓存条目数
- `ttl_seconds` — TTL(默认 3600 = 1h)
