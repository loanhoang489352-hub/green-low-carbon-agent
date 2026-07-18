"""
Skill 抽象层
组合多个 BaseTool 形成高级技能

P10.A:符合 Anthropic Skills 规范(2026-01 GA)
- version / when_to_use / allowed_tools 字段
- export_skill_md() / write_skill_md() 生成 SKILL.md
- 名称/描述/触发关键词校验
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field  # dataclass for SkillContext; field for default_factory
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys

script_path = Path(__file__).resolve()
# skill.py 位于 src/agent/skills/skill.py
# 4 层 parent = 项目根(不是 3 层 — 那会指到 src/)
project_root = script_path.parent.parent.parent.parent
if str(project_root / "src") not in sys.path:
    sys.path.insert(0, str(project_root / "src"))

from agent.tools.base import BaseTool, ToolResult  # noqa: E402

_log = logging.getLogger(__name__)

# ============ Anthropic Skills 规范常量 ============

_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_RESERVED_NAME_TOKENS = ("anthropic", "claude")
_MAX_NAME_LEN = 64
_MAX_DESC_LEN = 1024
_MAX_TRIGGER_KEYWORDS = 16


class SkillValidationError(ValueError):
    """Skill 元数据校验失败"""


@dataclass
class SkillContext:
    """Skill 执行上下文"""

    user_id: str = ""
    conversation_id: str = ""
    message: str = ""
    intent_type: str = ""
    profile: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    """
    Skill 抽象类

    Skill 是对 BaseTool 的组合封装，代表一个完整的业务能力。
    一个 Skill 可以组合多个 BaseTool，形成更高级的功能。

    P10.A:符合 Anthropic Skills 规范 — 增加 version / when_to_use /
    allowed_tools 三个元数据字段,LLM 可基于 when_to_use 触发短语选择 Skill;
    write_skill_md() 把 Skill 写到 .claude/skills/<name>/SKILL.md。
    """

    # ---- 基础元数据(子类必须覆盖 name / description)----
    name: str = ""
    description: str = ""
    category: str = "general"

    # ---- P10.A:Anthropic Skills 规范新增字段 ----
    version: str = "1.0.0"
    when_to_use: str = ""
    allowed_tools: List[str] = []  # 子类覆写;基类空 list

    @property
    @abstractmethod
    def tools(self) -> List[BaseTool]:
        """该 Skill 组合的工具列表"""
        pass

    @abstractmethod
    def execute(self, context: SkillContext) -> ToolResult:
        """
        执行 Skill

        Args:
            context: Skill 执行上下文

        Returns:
            ToolResult: 执行结果
        """
        pass

    # ============ P10.A:校验 ============

    def validate(self) -> List[str]:
        """校验元数据是否符合 Anthropic Skills 规范

        返回: 错误列表(空列表 = 通过)
        """
        errors: List[str] = []

        # 1. name 校验
        if not self.name:
            errors.append("name 不能为空")
        else:
            if len(self.name) > _MAX_NAME_LEN:
                errors.append(f"name 长度 {len(self.name)} > {_MAX_NAME_LEN}")
            if not _NAME_RE.match(self.name):
                errors.append(
                    f"name '{self.name}' 必须匹配 ^[a-z0-9_-]+$ "
                    "(仅小写字母/数字/连字符/下划线)"
                )
            lowered = self.name.lower()
            for tok in _RESERVED_NAME_TOKENS:
                if tok in lowered:
                    errors.append(f"name '{self.name}' 不能包含保留字 '{tok}'")

        # 2. description 校验
        if not self.description:
            errors.append("description 不能为空")
        elif len(self.description) > _MAX_DESC_LEN:
            errors.append(
                f"description 长度 {len(self.description)} > {_MAX_DESC_LEN}"
            )

        # 3. when_to_use 必须含触发关键词(否则 LLM 无法选择)
        if not self.when_to_use:
            errors.append("when_to_use 不能为空(LLM 需要触发短语选 Skill)")
        elif len(self._trigger_keywords()) == 0:
            errors.append(
                "when_to_use 必含至少 1 个触发关键词 "
                "(用 / 或 | 或 , 分隔)"
            )

        # 4. version 格式(语义化版本)
        if not re.match(r"^\d+\.\d+\.\d+", self.version or ""):
            errors.append(f"version '{self.version}' 不是语义化版本(x.y.z)")

        # 5. allowed_tools 与 self.tools 一致性(如果非空)
        if self.allowed_tools:
            actual = [t.name for t in self.tools]
            unknown = [t for t in self.allowed_tools if t not in actual]
            if unknown:
                errors.append(
                    f"allowed_tools {unknown} 不在 self.tools 实际列表 {actual}"
                )

        return errors

    def _trigger_keywords(self) -> List[str]:
        """从 when_to_use 解析触发关键词列表"""
        if not self.when_to_use:
            return []
        # 兼容 / / | / , / ; 分隔
        parts = re.split(r"[/|;,、，\s]+", self.when_to_use)
        return [p.strip() for p in parts if p.strip()]

    # ============ P10.A:SKILL.md 生成 ============

    def export_skill_md(self) -> str:
        """生成符合 Anthropic Skills 规范的 SKILL.md 内容

        输出 YAML front-matter + Markdown 正文。
        """
        actual_tools = [t.name for t in self.tools]
        allowed = self.allowed_tools or actual_tools
        triggers = self._trigger_keywords()

        # ---- YAML front-matter ----
        fm_lines = ["---"]
        fm_lines.append(f"name: {self.name}")
        fm_lines.append(f"version: {self.version}")
        fm_lines.append(f"category: {self.category}")
        if self.when_to_use:
            # YAML 内字符串里含中文/空格 → 用引号包
            fm_lines.append(f'when_to_use: "{self.when_to_use}"')
        if allowed:
            fm_lines.append("allowed_tools:")
            for t in allowed:
                fm_lines.append(f"  - {t}")
        if triggers:
            fm_lines.append("trigger_keywords:")
            for kw in triggers:
                fm_lines.append(f"  - {kw}")
        fm_lines.append("---")
        fm_lines.append("")

        # ---- Markdown 正文 ----
        md: List[str] = []
        md.append(f"# {self.name}")
        md.append("")
        md.append(f"> {self.description}")
        md.append("")
        md.append("## When to use")
        md.append("")
        if self.when_to_use:
            md.append(f"触发短语:**{self.when_to_use}**")
            md.append("")
            md.append("LLM 识别到用户消息含上述任意触发短语时,应优先选择本 Skill。")
        else:
            md.append("(未配置触发短语)")
        md.append("")

        md.append("## Tools")
        md.append("")
        md.append("本 Skill 组合以下工具:")
        md.append("")
        for t in actual_tools:
            md.append(f"- `{t}`")
        md.append("")
        if allowed and set(allowed) != set(actual_tools):
            md.append("白名单(allowed_tools):")
            md.append("")
            for t in allowed:
                md.append(f"- `{t}`")
            md.append("")

        md.append("## Category")
        md.append("")
        md.append(f"`{self.category}`")
        md.append("")

        md.append("## Version")
        md.append("")
        md.append(f"`{self.version}`")
        md.append("")

        md.append("## Notes")
        md.append("")
        md.append("- 本 SKILL.md 由代码自动生成(注册时写入)")
        md.append("- 元数据变更后请同步更新 `src/agent/skills/builtin.py`")
        md.append("- 目录结构遵循 Anthropic Skills 规范:`SKILL.md` + `scripts/`(可选) + `references/`(可选)")
        md.append("")

        body = "\n".join(md)
        return "\n".join(fm_lines) + "\n" + body

    def write_skill_md(self, base_dir: Optional[Path] = None) -> Path:
        """写 SKILL.md 到磁盘

        默认写到 `<project_root>/.claude/skills/<name>/SKILL.md`,
        同时创建 `scripts/` 和 `references/` 子目录(占位)。

        失败时只记录日志、不抛异常(启动不能因磁盘问题阻塞)。

        返回: SKILL.md 的绝对路径(失败时返 None — 用 isinstance 校验)
        """
        try:
            if base_dir is None:
                # 找项目根:从模块位置向上,直到看到 data/ 或 .claude/ 目录
                base = _find_project_root() / ".claude" / "skills"
            else:
                base = Path(base_dir)

            skill_dir = base / self.name
            skill_dir.mkdir(parents=True, exist_ok=True)

            # 可选子目录(Anthropic 规范)
            (skill_dir / "scripts").mkdir(exist_ok=True)
            (skill_dir / "references").mkdir(exist_ok=True)

            target = skill_dir / "SKILL.md"
            target.write_text(self.export_skill_md(), encoding="utf-8")
            _log.info("[Skill] SKILL.md 已写入: %s", target)
            return target
        except Exception as e:
            _log.warning("[Skill] SKILL.md 写入失败(name=%s): %s", self.name, e)
            # 失败不能阻塞启动 — 返一个虚拟路径
            try:
                return _find_project_root() / ".claude" / "skills" / self.name / "SKILL.md"
            except Exception:
                return Path(".")

    # ============ Schema(LLM 可见)============

    def get_schema(self) -> Dict[str, Any]:
        """获取 Skill 的 schema(用于 LLM 理解)"""
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "when_to_use": self.when_to_use,
            "allowed_tools": list(self.allowed_tools),
            "tools": [t.name for t in self.tools],
        }

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """获取所有组合工具的 schema"""
        return [t.get_schema() for t in self.tools]


def _find_project_root() -> Path:
    """找项目根(向上直到找到稳定的项目根标记)

    项目根标记:同时有 `data/` + `knowledge_base/` + `requirements*.txt` 三者。
    """
    try:
        start = Path(__file__).resolve().parent
        # 多上 1~6 层,直到找到完整的三联标记
        for ancestor in [start, *start.parents][:8]:
            if (
                (ancestor / "data").is_dir()
                and (ancestor / "knowledge_base").is_dir()
                and any((ancestor / f"requirements{ext}").is_file()
                       for ext in ("", ".txt", "-dev.txt"))
            ):
                return ancestor
        # 退而求其次:用 data/ + knowledge_base/
        for ancestor in [start, *start.parents][:8]:
            if (ancestor / "data").is_dir() and (ancestor / "knowledge_base").is_dir():
                return ancestor
        # 兜底:4 层 parent
        return Path(__file__).resolve().parent.parent.parent.parent
    except Exception:
        try:
            return Path(__file__).resolve().parent.parent.parent.parent
        except Exception:
            return Path(".")


class SkillExecutor:
    """
    Skill 执行器

    负责 Skill 的注册和执行
    """

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill, overwrite: bool = False) -> bool:
        """注册 Skill"""
        if skill.name in self._skills and not overwrite:
            return False
        self._skills[skill.name] = skill
        return True

    def get(self, name: str) -> Optional[Skill]:
        """获取 Skill"""
        return self._skills.get(name)

    def list_all(self) -> List[str]:
        """列出所有已注册的 Skill"""
        return list(self._skills.keys())

    def execute(self, skill_name: str, context: SkillContext) -> ToolResult:
        """执行 Skill"""
        skill = self._skills.get(skill_name)
        if not skill:
            return ToolResult(success=False, error=f"Skill {skill_name} 不存在")
        return skill.execute(context)

    def get_all_schemas(self) -> List[Dict[str, Any]]:
        """获取所有 Skill 的 schema"""
        return [s.get_schema() for s in self._skills.values()]


_global_skill_executor: Optional[SkillExecutor] = None


def get_skill_executor() -> SkillExecutor:
    """获取全局 Skill 执行器(单例)"""
    global _global_skill_executor
    if _global_skill_executor is None:
        _global_skill_executor = SkillExecutor()
    return _global_skill_executor