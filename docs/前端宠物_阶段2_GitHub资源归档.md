# 阶段 2: GitHub 资源归档

**时间**: 2026-06-14
**目标**: 筛选前端 Skill + 桌面宠物项目,二次改造可用

---

## 一、桌面宠物项目(子任务 2.2)— 8 个候选

| 排名 | 仓库 | ★ | 技术栈 | 适配 | 决策 |
|---|---|---|---|---|---|
| 1 | [Adrianotiger/desktopPet](https://github.com/Adrianotiger/desktopPet) | 1109 | C# + JS 网页版 | ⭐⭐⭐⭐⭐ | **必参考**(经典 eSheep) |
| 2 | [alvinunreal/openpets](https://github.com/alvinunreal/openpets) | 782 | TypeScript + Electron | ⭐⭐⭐⭐⭐ | **必参考**(SDK 架构) |
| 3 | [isHarryh/Ark-Pets](https://github.com/isHarryh/Ark-Pets) | 977 | Java | ⭐⭐ | 仅参考形态设计 |
| 4 | [rullerzhou-afk/clawd-on-desk](https://github.com/rullerzhou-afk/clawd-on-desk) | 4276 | JS | ⭐⭐ | 创意参考 |
| 5 | [ChaozhongLiu/DyberPet](https://github.com/ChaozhongLiu/DyberPet) | 815 | Python PySide6 | ⭐⭐ | 框架参考 |
| 6 | [shinyfluvre/Mate-Engine](https://github.com/shinyfluvre/Mate-Engine) | 3267 | ShaderLab 3D | ⭐ | 3D 太重,不采纳 |
| 7 | openpets/Pet-Format | - | TypeScript | ⭐⭐⭐⭐ | openpets 子包(JSON manifest) |
| 8 | VirtualCockroach | 714 | ActionScript | ⭐ | 淘汰 |

**选 1+2 为核心参考**。

---

## 二、Adrianotiger/desktopPet 关键借鉴(★1109)

- **资源规范**:1000×500 PNG sprite sheet + `animations.xml`
- **12 预制角色**:eSheep 7 色 + Bunny + Asuna + Neko + Pingus
- **网页版**:`desktopPetJS`(JS 1.8%)
- **核心能力**:拖拽/移动/状态切换/动作序列
- **改造方案**:不直接复用代码,提取 `animations.xml` 规范 → 我们做 JSON manifest

---

## 三、alvinunreal/openpets 关键借鉴(★782)

- **Pet JSON manifest**:`@open-pets/pet-format` 包
- **状态机**:`thinking`/`editing`/`testing`/`success`/`error`
- **MCP 集成**:`openpets_react` 工具触发 pet 动画
- **气泡安全**:MCP speech 脱敏
- **改造方案**:Pet JSON manifest 引用进 `src/pet/species.py` 配合前端渲染

---

## 四、前端 Skill(子任务 2.1)

虽未搜出"高 star AI Agent 前端专用 Skill",但**经典前端加载优化** 已知:

| Skill/技术 | 用途 | 集成方式 |
|---|---|---|
| **CSS preload + aspect-ratio** | 防 CLS,锁定精灵占位 | 加 .preload 标记 + width/height |
| **Promise.race 超时** | fetch 超时降级 | 5s 超时 → 静态占位 |
| **Web Animations API** | 兼容 emoji + CSS keyframe 备份 | fallbackAnimation |
| **localStorage 缓存** | 离线降级 + 进度 | 缓存最近状态 |
| **requestIdleCallback** | 非关键渲染延后 | 排行榜 / 季节延后加载 |

**筛选结论**: 我们已经有完整 5 形态 emoji + 6 状态 CSS 动画,不需要外部 Skill。已搜过的高 star 项目主要给"框架思路"参考,不直接集成代码(技术栈不同)。

---

## 五、改造方案最终敲定

| 改造项 | 来源 | 方案 |
|---|---|---|
| 5 形态 | Adrianotiger 12 角色规范 | 用 emoji + 备 PNG(后续可换) |
| 6 状态动画 | 自创 CSS keyframe | 6 keyframe,bob/wiggle/glow/shake/droop/blink |
| 状态机 | openpets JSON manifest | 复用 `src/pet/numeric_rules.py` 的 compute_pet_status |
| MCP 联动 | openpets MCP 工具 | 已有 `pet_react` 入口,后续轮实现 |
| 资源预加载 | CSS preload | 阶段 4 实施 |
| 加载进度 | 简单进度条 | 阶段 4 实施 |
| 弱网兜底 | Promise.race | 阶段 4 实施 |

---

## 六、子任务 2.3 资源筛选结论

| 决策 | 项 |
|---|---|
| ✅ 必参考 | desktopPet(eSheep),openpets(SDK) |
| ⏸ 后续 | sprite sheet 资源(需要美术) |
| ⏸ 后续 | Lottie 动画(需找开源"绿色精灵"Lottie JSON) |
| ❌ 排除 | Mate-Engine(3D 重), Ark-Pets(Java),VirtualCockroach(AS3) |

**评估**: 资源已足够,进入阶段 3 实施。
