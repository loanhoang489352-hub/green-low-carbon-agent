---
name: jev-decision
version: 1.0.0
category: reasoning
when_to_use: "需求判断/意图分类/多轮指代/Jev用法"
allowed_tools:
  - jev_route
trigger_keywords:
  - 需求判断
  - 意图分类
  - 多轮指代
  - Jev用法
---

# jev-decision

> Jev 只做结构化判断，不生成方案。需要了解用法先用 operation=guide 读取官方技能。operation=route 只判断用户需求，message 传用户原话，state 只传当前会话上下文。规则、计算、权限和执行留在代码；概率不是事实证据或写画像的授权。取消/填槽等已有确定规则不要重复调用；失败或不确定时澄清或回退原 LLM。一次仅作一个明确判断，不要循环调用来追求想要的答案。

## When to use

触发短语:**需求判断/意图分类/多轮指代/Jev用法**

LLM 识别到用户消息含上述任意触发短语时,应优先选择本 Skill。

## Tools

本 Skill 组合以下工具:

- `jev_route`

## Category

`reasoning`

## Version

`1.0.0`

## Notes

- 本 SKILL.md 由代码自动生成(注册时写入)
- 元数据变更后请同步更新 `src/agent/skills/builtin.py`
- 目录结构遵循 Anthropic Skills 规范:`SKILL.md` + `scripts/`(可选) + `references/`(可选)
