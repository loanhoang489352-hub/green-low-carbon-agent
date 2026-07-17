# 任务 2: 数值规则深度绑定 — 低碳收益直接驱动宠物成长

**设计时间**: 2026-06-14
**核心**: 复用 `src/user_profile/carbon_footprint.py` 的 calculate_* 函数,新增转发接口双写数据

---

## 一、行为→资源映射(精确表)

| 行为类型 | 减排系数 (kg CO2e) | 饱食 +Δ | 心情 +Δ | 活力 +Δ | 精灵币 +Δ | 经验 +Δ | 碎片 +Δ |
|---|---|---|---|---|---|---|---|
| **公交** | 0.21 /km | 0 | 3 | 8 | 2 | 12 | 0 |
| **步行** | 0.05 /km | 0 | 2 | 6 | 1 | 10 | 0 |
| **骑行** | 0.21 /km | 0 | 3 | 8 | 2 | 12 | 0 |
| **节电** | 0.785 /kWh | 8 | 2 | 0 | 5 | 8 | 0 |
| **节水** | 0.344 /吨 | 6 | 1 | 0 | 3 | 6 | 0 |
| **垃圾分类** | 0.5 /次 | 4 | 4 | 0 | 2 | 6 | 0 |
| **减塑** | 0.3 /次 | 2 | 10 | 0 | 0 | 5 | 1 |
| **旧物回收** | 2.0 /kg | 0 | 15 | 0 | 0 | 8 | 2 |
| **低碳采购** | 0.01 /¥ | 0 | 5 | 0 | 0 | 8 | 0 |
| **植树认养** | 5.0 /棵 | 5 | 20 | 0 | 0 | 20 | 3 |

> 设计逻辑:
> - **活力** 来自"身体力行"(出行类)
> - **饱食** 来自"日常节能"(节电/水/分类)
> - **心情** 来自"额外贡献"(减塑/回收/采购)
> - **碎片** 仅来自"进阶行为"(回收/植树),稀缺

---

## 二、每日获取上限(防沉迷 + 防通胀)

| 资源 | 每日上限 | 触发上限提示 |
|---|---|---|
| 经验 | +500 | 「今日经验已达上限,明天继续!🌟」 |
| 饱食 | +30(超过 100 截断) | 「我已经吃饱啦~💚」 |
| 心情 | +30(超过 100 截断) | 「今天心情很好!😊」 |
| 活力 | +30(超过 100 截断) | 「活力满满!💪」 |
| 精灵币 | +200 | 「今日金币已达上限」 |
| 碎片 | +10 | 「碎片积累中,距离下一形态不远了!✨」 |

---

## 三、等级阈值(1-50)与升级曲线

| 等级 | 累计经验阈值 | 累计 kg CO2e(估算) | 称号 |
|---|---|---|---|
| 1 | 0 | 0 | 碳种子 |
| 5 | 200 | ~30 | 萌芽精灵 |
| 10 | 800 | ~80 | 绿叶使者 |
| 15 | 1,800 | ~150 | 低碳新手 |
| 20 | 3,500 | ~250 | 节能达人 |
| 25 | 6,000 | ~400 | 减排先锋 |
| 30 | 9,500 | ~600 | 守护者 |
| 35 | 14,000 | ~850 | 绿色英雄 |
| 40 | 20,000 | ~1,200 | 碳中和卫士 |
| 45 | 28,000 | ~1,600 | 环保传奇 |
| **50** | **40,000** | **~2,200** | **碳中和圣灵** |

升级曲线公式(L ≥ 2):
```
exp_to_next(L) = 100 * (L ^ 1.6)
```
累计经验:
```
total_exp(L) = sum_{i=1}^{L-1} 100 * (i ^ 1.6)
```
- L=1→2: 100 exp
- L=2→3: 100*2^1.6 ≈ 303
- L=10→11: 100*10^1.6 ≈ 3,981
- L=49→50: 100*49^1.6 ≈ 73,000

---

## 四、状态值衰减(防闲置 + 鼓励持续)

每 24h 自动衰减(每次进入 agent 时检查):
- 饱食 -5
- 心情 -3
- 活力 -4

> 衰减最低到 0,不再继续降。衰减到 0 后精灵会"萎靡",提示用户完成低碳任务补给。

---

## 五、双写数据接口设计

### 5.1 转发接口入口
**位置**: `src/pet/pet_engine.py:PetEngine.apply_behavior_rewards()`

**签名**:
```python
def apply_behavior_rewards(
    self,
    user_id: str,
    behavior_type: str,        # "bus" / "walk" / "bike" / "electricity" / ...
    amount: float,             # 数值(km / kWh / 次数 / kg / 元)
) -> PetStateChangeResult:
    """任务2 入口:接收一条低碳行为 → 双写数据(用户报表 + 宠物状态)"""
    pass
```

### 5.2 复用 carbon_footprint

```python
from user_profile.carbon_footprint import CarbonFootprintCalculator

cf = CarbonFootprintCalculator()
# 复用现有 calculate_* 函数
if behavior_type == "bus":
    co2_saved = cf.calculate_travel_emission(distance=amount, vehicle_type="bus")
# ... 其他类型同理
```

### 5.3 双写流程

```python
def apply_behavior_rewards(self, user_id, behavior_type, amount):
    # 1) 调 carbon_footprint 算减排量(不破坏原计算)
    co2_saved = self._compute_co2(behavior_type, amount)

    # 2) 写用户碳收益报表(原有逻辑,不动)
    self._carbon_log.record(user_id, behavior_type, amount, co2_saved)

    # 3) 计算宠物资源奖励
    rewards = self._calc_rewards(behavior_type, amount)

    # 4) 应用每日上限
    rewards = self._cap_daily(user_id, rewards)

    # 5) 更新宠物状态
    new_state = self._update_pet_state(user_id, rewards)

    # 6) 写 pet_state_change_log(新增,任务2 主目标)
    self._log_state_change(user_id, behavior_type, amount, co2_saved, rewards, new_state)

    return PetStateChangeResult(
        co2_saved=co2_saved,
        rewards=rewards,
        new_state=new_state,
        level_up=new_state.level > old_state.level,
        appearance_change=new_state.appearance != old_state.appearance,
    )
```

### 5.4 不修改原 carbon_footprint
- ✅ **不改 `src/user_profile/carbon_footprint.py`**
- ✅ **不改 `src/user_profile/persistence.py`**
- ✅ **不改行为事件表 `behavior_events`**
- ✅ 全部新增代码在 `src/pet/` 目录

---

## 六、累计减排→形态/外观/栖息地阈值(任务 4 详细)

| 累计 kg CO2e | 解锁内容 |
|---|---|
| 0 | 初始幼体「碳种子」|
| 30 | 青年体「萌芽精灵」|
| 50 | 绿植小屋(栖息地 1) |
| 100 | 形态「绿叶使者」|
| 150 | 光伏小屋(栖息地 2) |
| 200 | 形态「守护者」|
| 400 | 森林营地(栖息地 3) |
| 500 | 形态「绿色英雄」|
| 800 | 形态「碳中和卫士」|
| 1000 | 形态「碳中和圣灵」+ 碳中和家园(栖息地 4) |
| 2000 | 形态「环保传奇」+ 限定装扮(全套) |

---

## 七、闭环

✅ 行为→资源映射 10 类全覆盖
✅ 每日上限(防沉迷)
✅ 等级曲线(指数式,避免后期过陡)
✅ 状态衰减(每日)
✅ 双写流程(原 carbon_footprint 0 改动)
✅ 累计减排阈值(任务 4 用)

**任务 2 完成,等待任务 3 启动。**
