# 安全策略

本文档说明绿色低碳智能体在生产部署中应遵守的安全规范,覆盖
**PII 脱敏 / 密钥管理 / 限流 / 审计日志 / 鉴权 / 传输** 6 个维度。

## 1. PII 处理(个保法 / GDPR 合规)

### 自动脱敏(P5-I.A)
落库前对所有**用户自由输入文本字段**自动过 PII 正则:

| 字段类型 | 字段位置 | 脱敏规则 |
|---|---|---|
| 手机号 | `feedback.comment` / `feedback.reason` / `behavior_events.context` / `behavior_events.event_data.*` / `carbon_footprint_log.metadata.*` / `user_achievements.metadata.*` | `13800001234` → `138****1234`(保留前 3 + 后 4) |
| 邮箱 | 同上 | `zhangsan@example.com` → `zhan***@example.com`(保留用户名前 4 + 完整域名) |
| 身份证 | 同上 | `110101199001011234` → `110101********1234`(保留前 6 + 后 4) |
| 银行卡 | 同上 | `6222021234567890` → `6222********7890`(保留前 4 + 后 4) |
| 详细地址 | 同上 | 截断到 12 字符 + `***` |

工具函数:`src/utils/pii.py` 的 `mask_pii()`(综合入口) /
`mask_pii_in_dict()`(递归 dict 节点)。

### 不在自动脱敏范围
- `accounts.username`:注册时正则约束为 `[a-zA-Z0-9_]+`(3-20 字符),无法含 PII
- `accounts.password_hash`:永远以 `$2...`(bcrypt)或 `$pbkdf2$...` 开头,不会泄露明文
- 嵌入向量(`user_memories.embedding`):已是 float32 BLOB,无可读 PII

### 二次脱敏
审计日志写入时,`detail` 字段也走 PII 脱敏(防 detail 中残留手机号等)。

## 2. 密码存储

- 算法:**bcrypt**(默认)+ **PBKDF2-SHA256 100k 轮** 兜底(bcrypt 不可用时)
- 落库字段:`accounts.password_hash`,**永不**在 API 响应中暴露
- 验证:`bcrypt.checkpw()` 或 `pbkdf2_hmac()` 验签,常时 O(密码 + salt)
- 失败响应:统一 `{"error": "用户名或密码错误"}`,**不区分**"用户不存在"和"密码错"

## 3. 密钥管理

### 占位符检测(P5-I.B)
启动时 `config._check_api_keys()` 扫描以下环境变量,
命中占位符则:
- `ENV=production` → `logger.error()`(醒目)
- 其他环境 → `logger.warning()`(静默)

占位符集合:`__SET_ME__` / `your_api_key_here` / `your-api-key` / `sk-xxx` /
`sk-XXXX` / `changeme` / `TODO` / `PLACEHOLDER`(大小写不敏感、子串匹配)。

### 强制项
- **生产部署**必须用 `docker run --env-file .env.prod`(避免 `.env` 落 git)
- **永不**提交 `.env`、`*.key`、`*.pem`、`credentials.json` 到 git
- 历史泄露:见 commit `0b06688`(P0 轮换 + git-filter-repo 清理)

### 密钥矩阵(必须设置)

```
OPENAI_API_KEY=sk-...        # OpenAI / DeepSeek(同 base)
DEEPSEEK_API_KEY=...         # 可选,显式配置时优先
ANTHROPIC_API_KEY=...        # 可选
MINIMAX_API_KEY=...          # 可选
HUGGINGFACE_TOKEN=hf_...     # sentence-transformers 下载(可 hf-mirror)
```

## 4. API 限流(P5-I.B)

- 默认:**60 req / 60s / IP**(可由 `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW` 调)
- 算法:滑动时间窗(Deque)+ 内存存储(进程重启清空)
- 反代头:`X-Forwarded-For` 第一个值会被当成客户端 IP
- 超限:HTTP 429 + `{"code": "RATE_LIMITED", "message": "...", "retry_after": N}`
- 限流**早于鉴权**,防止暴力破解
- 关闭:`RATE_LIMIT_ENABLED=false`(生产慎用)

## 5. 审计日志(P5-I.B)

### 写入位置
`accounts.db.audit_log` 表,Schema Registry 自动初始化。

### 触发条件
- **成功**:`POST /api/auth/{login,register,logout}`、`/api/chat/enhanced`、
  `/api/feedback`、`PUT /api/profile`、`/api/onboarding/*`、
  `/api/policy/sync`、`/api/knowledge/reload`
- **失败**:鉴权失败(401)+ 限流(429)+ 业务异常(APIError) + 兜底(500)

### 字段
```
id, user_id, action, target, ip, user_agent, status_code, detail, created_at
```

### 写入保证
- 失败时 `logger.warning(..., action=...)`,**不阻塞**主流程
- `detail` 自动过 PII 脱敏
- 无 TTL,长期保留(必要时手工归档)

## 6. 鉴权(P5-D)

### 鉴权中间件
所有路由除 `auth/register|login`、`/`、`/api/health|ready|metrics`、
`/api/rag/stats` 外**强制要求**:

```
Authorization: Bearer <session_id>
或
X-Session-Id: <session_id>
或(POST body)
{"session_id": "..."}
```

### session 生命周期
- TTL 7 天,过期自动作废
- `account_manager.cleanup_expired_sessions()` 可由 scheduler 周期触发
- `logout` 立即作废(不再接受该 session)

### 失败响应
统一 `401 UNAUTHORIZED`,**不**透露"用户不存在"或"密码错"。

## 7. 传输

### TLS / HTTPS
- 生产环境**必须**用 Nginx / Caddy 反代终止 TLS(`deploy/nginx.conf` 模板见 P5-J)
- HTTP/2 可选启用
- HSTS:反代层加 `Strict-Transport-Security: max-age=31536000; includeSubDomains`

### CORS
`CORS_ORIGINS` 显式白名单(逗号分隔),默认 `http://localhost:3000,http://127.0.0.1:3000`。
**生产不要**用 `*` 或留空,避免 CSRF。

### 前端 XSS 防护(P6.S.23)
`web/index.html` 是单体内嵌 JS,所有 `innerHTML` 拼接用户/后端可控字段都必须过 `escapeHtml()`
(覆盖 `& < > " ' \`` 6 类字符),在 PR-1 中加固:

| 入口 | 修法 |
|------|------|
| `addMessage` 渲染助手消息 | `formatContent(content)` 先 `escapeHtml(String(content))` 再做 markdown 替换 |
| 助手的 `recommendation.action` / `category` / `examples` | 模板里 `${escapeHtml(...)}` |
| 助手的 `suggestion` 按钮 | 旧 `onclick="sendQuickMessage('${s.replace(/'/g, "\\'")}')"` 拼接(只转单引号不全)<br>→ 改 `data-suggestion="${escapeHtml(s)}"` + `setupChatContainerDelegation()` 单一 click listener |
| 助手的 `knowledgeRefs` | `escapeHtml(typeof k === 'string' ? k : (k.title \|\| k.name \|\| ...))` |
| 政策列表 `policies.title/source/summary/key_points` | 全部 `escapeHtml(...)` |
| 画像 `ctx.behavior_stage / basic_info_summary` | 全部 `escapeHtml(...)` |
| 反馈按钮(comment / reason) | 改 `data-fb` + `data-msg-id` + 事件委托,无拼接 |

**触发场景示例**(修复前会执行 JS):
- LLM 答 `<script>alert(1)</script>` → DOM 直接执行
- 第三方政策源 `policy.title = '<img onerror=alert(1)>'` → DOM 注入
- 助手建议文本 `'); evil(); //` → onclick 内代码执行

**验证**:`tests/test_p6s23_xss_helpers.py` 14 个测试 + `test_p6s23_intent_location.py` 10 个测试
覆盖 escapeHtml 完整性、`formatContent` 顺序、所有内联 onclick 已迁移、crypto.randomUUID 替代等。

### 事件委托替代内联 onclick
PR-1 之前 30+ 处内联 `onclick="..."` 既不安全(转义不全)也难维护。
PR-1 之后:
- `chat-container` 上挂一个 click listener,按 `data-fb` / `data-suggestion` / `data-retry` / `data-msg-id` 派发
- 其余 fixed 元素(header / 设置按钮 / Tab 切换)继续用 `addEventListener`(本就正确)

## 8. 已知限制

- **内存限流不跨进程**:单机部署 OK,多 worker(Nginx upstream)需用 Redis 替代
- **审计日志无 TTL**:长期保留,需手工归档
- **PII 规则基于正则**:非结构化/外语 PII 可能漏检(限检"知足",要 100% 仍需 NER)
- **session 共享**:同账号多端登录产生多个 session,无强制互踢
- **CSRF 保护**:依赖 `Authorization: Bearer` 头 + `Content-Type: application/json` 双重约束;
  反代层不要把 GET 转成带 body 的请求

## 9. 事件 / 漏洞上报

发现安全问题:本仓库 GitHub Issues(私有) + 邮件给维护者。
请勿在公开 Issue 中贴具体 PoC。

## 10. 依赖管理(P6.K)

### 双 requirements.txt 分离

- `requirements.txt` — 生产依赖(锁最低版本,部署到生产)
- `requirements-dev.txt` — 开发依赖(pytest / ruff / black / mkdocs 等)
- 部署只装 `requirements.txt`,不装 dev 依赖,减少攻击面

### 版本锁定策略

- `requirements.txt` 用 `>=` 锁**最低**版本(让 pip 解析最新兼容版本)
- 生产环境推荐用 `pip-compile`(dev 依赖)生成 `requirements.lock`(Pinned + Hash)
- CI 跑 `pip install --require-hashes -r requirements.lock`(防止依赖混淆攻击)

### 已知供应链风险

- **chromadb**:依赖较多 native 库(grpcio / pyarrow),版本冲突时建议 `pip install --no-deps` + 手动装
- **sentence-transformers**:首次运行下载约 100MB 模型,需访问 huggingface.co
- **langgraph-checkpoint-sqlite**:LangGraph 官方 SQLite checkpointer,版本需与 langgraph 匹配

### 第三方许可证

- 整体 License: **MIT**(见 `LICENSE` 文件)
- 第三方依赖许可证:用 `pip-licenses` 自动生成 `THIRD_PARTY_NOTICES.md`
  ```bash
  pip install pip-licenses
  pip-licenses --format=markdown --output-file=THIRD_PARTY_NOTICES.md
  ```

### 依赖更新策略

- **安全补丁**:立即更新,跑全量回归(235+ 测试)
- **功能更新**:每月底 review PyPI releases,小版本直接升,大版本评估
- **依赖审计**:`pip-audit` 跑 CVE 扫描(可加进 CI)
  ```bash
  pip install pip-audit
  pip-audit -r requirements.txt
  ```

### 私有依赖(如未来有)

- `pip.conf` 配私有 index:`[global] index-url = https://pypi.your-org.com/simple/`
- `requirements.lock` 用 `pip download` 生成 hash 锁
- CI 跑 `pip install --require-hashes`
