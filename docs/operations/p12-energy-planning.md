# P12 节能规划 — 运维手册

> 给运维 / SRE。问题发生时查这里。

---

## 1. P12 在生产环境的形态

**模块位置**:`src/agent/energy/`(5 个核心模块)

**数据库**:
- `data/households.db` — `household_profiles` / `household_plans` / `energy_daily_streak` 3 张表
- `data/energy_actions.db` — `energy_plans` / `energy_completions` 2 张表
- WAL 模式 + busy_timeout=5000ms

**API 端点**:
- `POST /api/energy/profile` — 录画像
- `POST /api/energy/plan` — 出方案
- `GET  /api/energy/today` — 今日卡
- `POST /api/energy/actions/{id}/complete` — 标完成
- `GET  /api/energy/stats` — 累计统计
- `POST /api/household/delegation` — 改级别
- `GET  /api/energy/actions` — 列 pending/done

**Skill 暴露**:`energy-planning` (在 `src/agent/skills/builtin.py`),`/api/mcp/status` 可查

**关键文件路径速查**:
- 核心:`src/agent/energy/{models,policies,planner,tracker,delegation,household_store}.py`
- API:`src/server/routers/energy.py`
- Skill:`src/agent/skills/energy_planning_skill.py`
- 测试:`tests/test_energy_{planner,api,e2e,no_hallucination}.py`
- 评估:`scripts/eval_energy.py`
- Golden set:`tests/eval/energy_golden_set.jsonl`

---

## 2. 关键指标(KPI)

| 指标 | 目标 | 采集方式 |
|---|---|---|
| eval hit_rate@5 | ≥ 1.0 | `python scripts/eval_energy.py` |
| eval hallucination_rate | = 0 | 同上(必须 0,出现就告警) |
| eval coverage | = 1.0 | 同上(3 类全有) |
| eval realism | = 1.0 | 同上(数字合理) |
| pytest 通过率 | ≥ 95% | `pytest tests/test_energy_*.py` |
| GUARD 触发率 | < 5%(正常画像应几乎不触发) | `/api/energy/plan` 响应里的 blocked=true 比例 |
| streak 分布 | 70%+ 用户 streak ≥ 7 天 | `ActionTracker.get_streak` |
| 委托级别分布 | level 1 / 2 占 70%+(默认值) | `household_profiles.delegation_level` group by |

**怎么查**:
```bash
# 跑完整评估
python scripts/eval_energy.py 2>&1 | tail -30

# pytest 通过率
pytest tests/test_energy_*.py --tb=no -q 2>&1 | tail -5

# GUARD 触发率(自定义 SQL)
sqlite3 data/households.db "SELECT blocked, COUNT(*) FROM household_plans GROUP BY blocked;"

# 委托级别分布
sqlite3 data/households.db "SELECT delegation_level, COUNT(*) FROM household_profiles GROUP BY delegation_level;"
```

---

## 3. 告警规则

| 触发条件 | 严重度 | 动作 |
|---|---|---|
| `eval hallucination_rate > 0` | **P0 紧急** | 立即回滚,排查 planner 改动 |
| `eval hit_rate < 0.95` | P1 | 检查 `APPLIANCE_SAVINGS` / `CITY_TIER_PRICING` 表是否被改 |
| `eval coverage < 1.0` | P1 | 某类目 action 缺失,查 `_PROFILE_TO_ACTIONS` 映射 |
| `pytest` 新增失败 | P2 | 看 trace,可能是 fixture 或 mock 变化 |
| `GUARD` 触发率 > 5% | P3 | 用户画像质量下降,可能 onboarding 出问题 |
| `data/households.db` 大小 > 100MB | P3 | 可能是 plan 冗余,运行清理脚本 |
| `/api/energy/plan` P95 > 2s | P2 | 7 个城市表查 OK,看 RAG 集成是否被调用 |
| streak 平均 < 3 天 | P3 | 引导策略问题,看 on_success 推送 |

---

## 4. 5 个常见故障 + 排查

### 症状 1:`/api/energy/plan` 返回 `blocked: true` 但用户画像看起来正常
**原因**:planner 触发 GUARD 守卫,可能字段值异常(比如 `monthly_electricity_kwh` 是负数或超 5000)
**排查**:
```bash
# 查用户的画像
sqlite3 data/households.db "SELECT * FROM household_profiles WHERE user_id='USR_ID';"

# 看 warning 具体内容
curl -s -X POST http://localhost:8000/api/energy/plan -H "Authorization: Bearer $TOKEN" | jq .warning
```
**修复**:让用户重新录入画像,或人工调整极端值

### 症状 2:eval 跑出 `hallucination_rate > 0`
**原因**:某条 action 的 `saving_*` 数字没在 `APPLIANCE_SAVINGS` 表里,planner 编造了
**排查**:
```bash
# 找 source_ref 不在白名单的 action
python -c "
import json
with open('tests/eval/energy_golden_set.jsonl') as f:
    for line in f:
        case = json.loads(line)
        # 跑 planner 看每个 action 的 source_ref
        ...
"
```
**修复**:补 `APPLIANCE_SAVINGS` 表里的数字,或删除该 action_key

### 症状 3:`tests/test_energy_no_hallucination.py` 新增失败
**原因**:planner 改了 GUARD 行为,守卫条件变了
**排查**:
```bash
pytest tests/test_energy_no_hallucination.py -v --tb=long 2>&1 | head -50
```
**修复**:看是 `GUARD_*` 不触发还是触发条件错,改 `planner.py:_check_guards` 或 `planner.py:generate_plan` 守卫顺序

### 症状 4:`/api/energy/today` 返空
**原因**:用户没有 active 方案(可能 plan 被 GUARD 或 status=blocked)
**排查**:
```bash
sqlite3 data/households.db "SELECT id, status, blocked, warning FROM household_plans WHERE user_id='USR_ID' ORDER BY created_at DESC LIMIT 5;"
```
**修复**:让用户调 `POST /api/energy/plan` 重出方案,或检查 `household_plans` 加载逻辑

### 症状 5:数据写入失败 / DB 锁
**原因**:SQLite 写并发(虽然 P12 用 P6.E 连接池,但并发突发)
**排查**:
```bash
tail -50 logs/agent.log | grep -i "database is locked"
sqlite3 data/households.db ".timeout 10000"
```
**修复**:重启服务,确认 `db/connection.py` 池 TTL=60s 生效

---

## 5. 应急操作(无需重启)

### 强制重建某用户的方案
```bash
sqlite3 data/households.db "DELETE FROM household_plans WHERE user_id='USR_ID';"
curl -X POST http://localhost:8000/api/energy/plan -H "Authorization: Bearer $TOKEN"
```

### 临时关闭 Skill(LLM 不再调用)
改 `src/agent/skills/builtin.py`,把 `EnergyPlanningSkill` 注释掉,重启服务。

### 临时跳过 eval CI gate
把 `scripts/eval_energy.py` 的 `sys.exit(1 if ...) ` 改为 `sys.exit(0)`(仅紧急,完事改回)。

### 清空所有 blocked plan
```bash
sqlite3 data/households.db "UPDATE household_plans SET status='draft' WHERE blocked=1;"
# 这些用户重跑 plan 就能拿到正常方案
```

### 备份 / 恢复
```bash
# 备份
sqlite3 data/households.db ".backup /tmp/households_$(date +%Y%m%d).db"

# 恢复(停服务)
pkill -f "python main.py"
cp /tmp/households_20260101.db data/households.db
python src/main.py
```

---

## 6. 维护任务

| 频率 | 任务 | 命令 |
|---|---|---|
| **每周** | 检查 data/households.db 大小,清理 30 天前的 completed plan | `sqlite3 data/households.db "DELETE FROM household_plans WHERE status='completed' AND created_at < datetime('now', '-30 day');"` |
| **每月** | 检查 7 城市阶梯电价表是否过期 | 看 `policies.py` 的 `source_ref` 字段,对比 `knowledge_base/policy/` 实际内容 |
| **每月** | 跑 eval 看 hit_rate 是否退化 | `python scripts/eval_energy.py` |
| **每季度** | 更新 13 个电器节能潜力表 | 查 GB 标准 / 厂商数据,更新 `APPLIANCE_SAVINGS` |
| **每季度** | 跑 `tests/eval/skills_golden_set.jsonl` 138 条 query 验证 trigger 仍准 | `python scripts/eval_skills.py` |
| **每年** | 全面 review GUARD 守卫条件是否仍合理 | 看 `planner.py:_check_guards` |

---

## 7. 升级 / 回滚

### 升级流程
1. 改 `policies.py` 阶梯电价 / 电器标准
2. 跑 `python scripts/eval_energy.py` 验证 hit_rate 仍 ≥ 1.0
3. 跑 `pytest tests/test_energy_*.py` 验证 184 个全过
4. 跑 `scripts/eval_retrieval.py` 验证 RAG 没退化(P5-G)
5. commit + push

### 回滚
```bash
# 找最近 3 个 P12 commit
git log --oneline --grep="P12" -5

# 回滚到上一个稳定点(假设是 41d21fb 之前)
git revert 78ff5a7 41d21fb 76d1f58 --no-edit

# 推
git push origin master
```

### 数据库 schema 迁移
P12 用 P5-G 风格的 Schema Registry(`src/db_schema.py`)。新增字段:
```python
# 在 db_schema.py 找到 ENERGY_SCHEMA 字典
"household_profiles": """
    CREATE TABLE IF NOT EXISTS household_profiles (
        ...
        my_new_field TEXT DEFAULT NULL  -- 新字段
    );
"""
```
然后重启服务,P5-G 会自动 ALTER(若不支持回退到手动 SQL)。

---

## 8. 关键问题排查(快速对照)

| 现象 | 看这里 |
|---|---|
| 用户说"AI 给我乱编" | `policies.APPLIANCE_SAVINGS` + `planner.GUARD_*` |
| 用户说"AI 不听话,自己动手" | `household_profiles.delegation_level` 是否被改 |
| 用户说"AI 推荐不适合我家" | `household_profiles` 数据是否准确(让他重填) |
| 用户说"AI 重复推荐同一动作" | `ActionTracker.get_completion_stats` 看是否已 done |
| 测试 `pytest_e2e` 1 个 fail | 通常是 `test_plan_covers_3_categories_every_city` 的 `appliances=[]` 现在走 GUARD,改用 `appliances=['灯']` |

---

## 附录 A:数据流图

```
用户输入
  → POST /api/energy/profile
  → household_profiles 表(UPSERT)
  → HouseholdProfile dataclass

用户调 plan
  → POST /api/energy/plan
  → load_profile → profile
  → planner.generate_plan(profile)
    → _check_guards(profile) → 4 个 GUARD 检查
    → guard 触发? → 返 blocked plan (200)
    → guard 通过? → 查 CITY_TIER_PRICING
                  → 查 APPLIANCE_SAVINGS (电器关键词)
                  → _ensure_category_min_two
                  → 拼装 5-10 个 EnergyAction
                  → 返 EnergyPlan (status=draft, blocked=False)
  → 委托级别决策
    → level 0: save_plan + status=active
    → level 1: 返 plan,等用户说"激活"
    → level 2: 返 3 个变体,等用户选
    → level 3: 返 plan,不存
  → household_plans 表

用户做
  → GET /api/energy/today
  → 抽 active plan.actions
  → 按 difficulty 排序,抽前 3 + 1 提醒
  → 返 TodayCard

用户标完成
  → POST /api/energy/actions/{id}/complete
  → ActionTracker.mark_completion(user_id, action_id, level)
    → level = full / partial → streak + 1
    → level = none → streak 不变
  → energy_completions 表
  → energy_daily_streak 表

用户查统计
  → GET /api/energy/stats
  → ActionTracker.get_completion_stats(user_id)
  → 返 {"total_saving_cny": X, "total_saving_co2_kg": Y, "streak": N, "..."}
```

---

## 附录 B:一行命令速查

```bash
# 跑所有 P12 测试
pytest tests/test_energy_*.py -v

# 跑评估
python scripts/eval_energy.py

# 看某用户当前 plan
sqlite3 data/households.db "SELECT * FROM household_plans WHERE user_id='USR_ID' ORDER BY created_at DESC LIMIT 1;"

# 看所有 GUARD 触发
sqlite3 data/households.db "SELECT user_id, warning, created_at FROM household_plans WHERE blocked=1 ORDER BY created_at DESC LIMIT 20;"

# 看 streak 排行
sqlite3 data/households.db "SELECT user_id, COUNT(*) AS days FROM energy_daily_streak WHERE has_activity=1 GROUP BY user_id ORDER BY days DESC LIMIT 10;"

# 备份
sqlite3 data/households.db ".backup /tmp/households_\$(date +%Y%m%d).db"
```
