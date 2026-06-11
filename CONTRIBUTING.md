# 贡献指南(Contributing Guide)

> 绿色低碳智能体欢迎所有形式的贡献:bug 报告、文档改进、新功能、性能优化、翻译、安全审计。
> 本指南说明如何高效协作。

## 目录

- [行为准则](#行为准则)
- [报告 Bug](#报告-bug)
- [提功能请求](#提功能请求)
- [提 PR(Pull Request)](#提-pr)
- [开发环境](#开发环境)
- [代码规范](#代码规范)
- [测试要求](#测试要求)
- [Commit 规范](#commit-规范)
- [审阅流程](#审阅流程)
- [发布流程](#发布流程)

---

## 行为准则

- 尊重他人,专业沟通
- 关注技术,不针对人
- 接受建设性反馈,假设对方出于善意
- 报告问题对事不对人

## 报告 Bug

提 GitHub Issue,**必填**:
1. **环境**:Python 版本 / OS / 关键依赖版本(`pip freeze | head -30`)
2. **复现步骤**:最小可执行命令
3. **期望行为**:应该发生什么
4. **实际行为**:实际发生了什么
5. **日志/截图**:`data/logs/app.log` 末尾 50 行

如果是**安全漏洞**,**不要**开公开 Issue — 邮件维护者。

## 提功能请求

提 GitHub Issue,**必填**:
1. **动机**:解决什么问题 / 满足什么场景
2. **方案**:大方向设计(可选,无也行)
3. **替代方案**:考虑过哪些其他方法
4. **影响范围**:哪些模块 / 哪些用户会受益

小改动可直接提 PR(小步快跑),大改动先开 Issue 讨论。

## 提 PR

1. Fork → 创建分支(`git checkout -b feat/my-feature`)
2. 写代码 + 写测试(P6 起新增 100+ 测试,测试覆盖要 ≥ 80%)
3. 跑回归:`pytest tests/ -v --tb=short`(应全过)
4. 跑 `make doctor`(应 5/5 过)
5. 跑 `ruff check src/`(应 0 错误)
6. Commit 规范:[Commit 规范](#commit-规范)
7. Push + 开 PR,描述:
   - 解决了哪个 Issue
   - 改动列表
   - 测试覆盖
   - 截图(如 UI 改动)
8. 等 CI 绿 + 1 个 reviewer 通过

## 开发环境

```bash
# 1. 克隆
git clone https://github.com/loanhoang489352-hub/green-low-carbon-agent.git
cd green-low-carbon-agent

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# 3. 装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入真实 API key(或设 LLM_MOCK=true 用 mock)

# 5. 初始化数据库(自动,启动时创建)
cd src && python main.py
```

## 代码规范

### 风格
- 遵循 PEP 8 + ruff 自动格式化
- 行宽 100(非 79)
- docstring 用中文(项目主语言)
- 函数命名 snake_case,类 PascalCase

### 类型提示
- 新代码必须含类型提示
- 用 `Optional[X]` / `List[X]` / `Dict[K, V]`
- 不需要 mypy 严格通过(legacy 代码还没补)

### 注释
- **Why > What**:解释为什么,不只是 what
- 复杂逻辑必须有 inline 注释
- TODO 加作者 + 日期: `# TODO(username, 2026-06-11): 优化 X`

### 错误处理
- 业务异常用 `APIError("CODE", "消息")` (P5-E 统一规范)
- 不暴露栈给客户端(P5-E 兜底)
- 关键路径 try/except + logger.warning,不静默吞

## 测试要求

### 覆盖率
- 新增模块/函数:**必须有**对应测试
- 改动老代码:同步更新对应测试
- 总体覆盖率目标 ≥ 80%(P6 当前 254+ 测试)

### 测试位置
- 单元测试:`tests/test_<module>.py`
- 端到端:`tests/test_p<X><letter>_*.py`(P0-P6 阶段命名)
- 评估脚本:`tests/eval/`

### 跑测试
```bash
# 全量
pytest tests/ -v

# 单文件
pytest tests/test_p6l_web_i18n.py -v

# 单个测试
pytest tests/test_p6l_web_i18n.py::test_i18n_js_dict_covers_zh_en -v

# 含覆盖率
pytest tests/ --cov=src --cov-report=term-missing
```

## Commit 规范

我们用 **Conventional Commits**(简化版):

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type
- `feat` — 新功能
- `fix` — bug 修复
- `perf` — 性能优化
- `refactor` — 重构(无功能变化)
- `docs` — 文档
- `test` — 测试
- `chore` — 杂项(配置 / 依赖)

### Scope(可选)
- 模块名:`auth` / `agent` / `llm` / `db` / `server` / `web`
- 阶段:`p5` / `p6` / `p5-d` / `p6-h`

### Subject
- 50 字以内
- 祈使语气:"add" / "fix" / "refactor"(非 "added" / "fixed")
- 首个字母不大写
- 末尾不加句号

### Body
- 解释**为什么**改(不是"做了什么")
- 关联 Issue / 任务
- 复杂改动加分段

### Footer
- `Closes #123` / `Refs #456`
- `BREAKING CHANGE: 描述`(不向后兼容时)

### 示例

```
feat(auth): P6.A P5-D 鉴权真落地 — 敏感路由全部需 Bearer session_id

P5-D 写了中间件 + verify_token + 17 个测试,但 30+ add_route 全部
显式 auth_required=False(plan 推迟到 P6)。

把 22 个敏感路由切到鉴权:
- chat/feedback/profile/personalization/stats/memory/onboarding-answer
- 公共端点保持 public(health/ready/metrics/auth-register)

加 test_e2e_real_auth.py 全量覆盖(401/有效 token 200)
```

## 审阅流程

1. PR 提 → 自动跑 CI(测试 + ruff)
2. Reviewer 评审(看代码 + 跑测试)
3. 反馈 → 作者改 → 再 review
4. 1 个 reviewer 通过 + CI 绿 → 合并

Reviewer 关注:
- 代码逻辑正确性
- 测试覆盖
- 文档更新(对应变更)
- 不破坏现有 API 兼容(除非 BREAKING CHANGE)
- 性能影响(大改动 / 热点路径)
- 安全考虑(用户输入 / 权限)

## 发布流程

1. 更新 `CHANGELOG.md`(已有)
2. 跑全量回归 + 性能基线
3. 打 tag:`git tag -a v2.X.Y -m "P6.X 总结"`
4. 推 tag:`git push --tags`
5. GitHub Release(自动 / 手动)
6. 更新 `docs/CHANGELOG.md` 反映版本

## 联系方式

- GitHub Issues:功能请求 / bug 报告
- GitHub Discussions:一般讨论 / 提问
- 邮件:安全问题 / 私有合作

---

**谢谢贡献!** 一起让绿色低碳智能体变得更好 🌱
