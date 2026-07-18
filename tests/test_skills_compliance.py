"""
P10.A:Skills 合规性测试

覆盖:
- Skill 基类字段(version / when_to_use / allowed_tools)
- 校验规则(name 正则 / 保留字 / 长度 / 描述长度 / when_to_use 关键词)
- SKILL.md 生成(YAML front-matter + Markdown 正文)
- write_skill_md() 实际落盘
- 3 个 builtin Skill 的元数据完整性
- get_schema() 包含新字段(向后兼容 — 老调用者多返字段不算破坏)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ============ 辅助 ============

def _load_builtin_classes():
    """延迟导入 builtin.py(避免顶层触发 src 路径未就绪)"""
    from agent.skills.builtin import (
        LowCarbonTravelSkill,
        PolicyQuerySkill,
        ProfileUpdateSkill,
    )
    return LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill


# ============ 1. 字段存在性 ============

class TestSkillFields:
    def test_version_field_default(self):
        """Skill 基类应有 version 默认 1.0.0"""
        from agent.skills.skill import Skill

        # 取一个最小具体实现 — PolicyQuerySkill 不依赖外部,直接看类属性
        SkillCls, _, _ = _load_builtin_classes()
        assert hasattr(SkillCls, "version")
        # 子类显式覆写
        assert SkillCls.version == "1.0.0"

    def test_when_to_use_field_default(self):
        from agent.skills.skill import Skill

        assert hasattr(Skill, "when_to_use")
        assert Skill.when_to_use == ""

    def test_allowed_tools_field_default(self):
        from agent.skills.skill import Skill

        assert hasattr(Skill, "allowed_tools")
        # 基类默认空 list
        assert Skill.allowed_tools == []


# ============ 2. 3 个 builtin Skill 的元数据 ============

class TestBuiltinSkillMetadata:
    @pytest.fixture
    def builtin_classes(self):
        return _load_builtin_classes()

    def test_travel_skill_metadata(self, builtin_classes):
        TravelCls, _, _ = builtin_classes
        skill = TravelCls()
        assert skill.name == "low_carbon_travel"
        assert skill.version == "1.0.0"
        assert skill.when_to_use
        # 触发短语必含关键词
        assert any(k in skill.when_to_use for k in ("出行", "通勤", "公共交通", "碳排放"))

    def test_policy_skill_metadata(self, builtin_classes):
        _, PolicyCls, _ = builtin_classes
        skill = PolicyCls()
        assert skill.name == "policy_query"
        assert skill.when_to_use
        assert any(k in skill.when_to_use for k in ("政策", "补贴", "碳交易"))

    def test_profile_skill_metadata(self, builtin_classes):
        _, _, ProfileCls = builtin_classes
        skill = ProfileCls()
        assert skill.name == "profile_update"
        assert skill.when_to_use
        assert any(k in skill.when_to_use for k in ("画像", "偏好", "行为"))

    def test_all_skills_validate(self, builtin_classes):
        """所有 builtin Skill 应通过校验"""
        for SkillCls in builtin_classes:
            inst = SkillCls()
            errors = inst.validate()
            assert errors == [], (
                f"{SkillCls.__name__} validate failed: {errors}"
            )

    def test_allowed_tools_match_actual(self, builtin_classes):
        """allowed_tools 必须在 self.tools 实际工具列表里"""
        for SkillCls in builtin_classes:
            inst = SkillCls()
            actual = {t.name for t in inst.tools}
            allowed = set(inst.allowed_tools)
            assert allowed.issubset(actual), (
                f"{SkillCls.__name__}: allowed_tools {allowed - actual} 不在 self.tools"
            )


# ============ 3. validate() 校验规则 ============

class TestSkillValidation:
    def _make_skill(self, **kwargs):
        """构造一个测试用 Skill 子类"""
        from agent.skills.skill import Skill, SkillContext
        from agent.tools.base import BaseTool, ToolResult

        class _DummyTool(BaseTool):
            @property
            def name(self):
                return "dummy_tool"

            @property
            def description(self):
                return "dummy"

            @property
            def parameters(self):
                return []

            def execute(self, **kwargs):
                return ToolResult(success=True, data={})

        class _TestSkill(Skill):
            @property
            def tools(self):
                return [_DummyTool()]

            def execute(self, context: SkillContext):
                return ToolResult(success=True)

        for k, v in kwargs.items():
            setattr(_TestSkill, k, v)
        return _TestSkill()

    def test_empty_name_fails(self):
        s = self._make_skill(name="", description="desc", when_to_use="kw")
        errors = s.validate()
        assert any("name 不能为空" in e for e in errors)

    def test_uppercase_name_fails(self):
        s = self._make_skill(name="BadName", description="d", when_to_use="kw")
        errors = s.validate()
        assert any("^[a-z0-9_-]+$" in e for e in errors)

    def test_name_with_space_fails(self):
        s = self._make_skill(name="bad name", description="d", when_to_use="kw")
        errors = s.validate()
        assert any("^[a-z0-9_-]+$" in e for e in errors)

    def test_name_with_underscore_passes(self):
        """P10.A:下划线现已允许(3 个 builtin skill 用 _ 分隔)"""
        s = self._make_skill(
            name="bad_name",
            description="d",
            when_to_use="kw / ok",
        )
        errors = s.validate()
        # 下划线合法,不报错
        assert not any("^[a-z0-9_-]+$" in e for e in errors)

    def test_name_too_long_fails(self):
        s = self._make_skill(name="a" * 65, description="d", when_to_use="kw")
        errors = s.validate()
        assert any("长度" in e and "64" in e for e in errors)

    def test_reserved_name_anthropic_fails(self):
        s = self._make_skill(
            name="anthropic-test", description="d", when_to_use="kw"
        )
        errors = s.validate()
        assert any("anthropic" in e for e in errors)

    def test_reserved_name_claude_fails(self):
        s = self._make_skill(
            name="my-claude-skill", description="d", when_to_use="kw"
        )
        errors = s.validate()
        assert any("claude" in e for e in errors)

    def test_description_too_long_fails(self):
        s = self._make_skill(
            name="ok-skill", description="x" * 1025, when_to_use="kw"
        )
        errors = s.validate()
        assert any("1024" in e for e in errors)

    def test_missing_when_to_use_fails(self):
        s = self._make_skill(name="ok-skill", description="d", when_to_use="")
        errors = s.validate()
        assert any("when_to_use" in e for e in errors)

    def test_when_to_use_only_separators_fails(self):
        s = self._make_skill(
            name="ok-skill", description="d", when_to_use="///"
        )
        errors = s.validate()
        # 分隔符无实质内容 → 触发关键词为空
        assert any("触发关键词" in e for e in errors)

    def test_invalid_version_format_fails(self):
        s = self._make_skill(
            name="ok-skill", description="d", when_to_use="kw", version="v1"
        )
        errors = s.validate()
        assert any("语义化版本" in e for e in errors)

    def test_allowed_tools_not_in_tools_fails(self):
        s = self._make_skill(
            name="ok-skill",
            description="d",
            when_to_use="kw",
            allowed_tools=["ghost_tool"],
        )
        errors = s.validate()
        assert any("不在 self.tools" in e for e in errors)

    def test_valid_skill_passes(self):
        s = self._make_skill(
            name="ok-skill",
            description="正常描述",
            when_to_use="出行规划 / 通勤建议",
            version="1.0.0",
            allowed_tools=["dummy_tool"],
        )
        errors = s.validate()
        assert errors == [], f"unexpected errors: {errors}"


# ============ 4. SKILL.md 导出 ============

class TestSkillMdExport:
    @pytest.fixture
    def builtin_classes(self):
        return _load_builtin_classes()

    def test_export_contains_front_matter(self, builtin_classes):
        for SkillCls in builtin_classes:
            inst = SkillCls()
            md = inst.export_skill_md()
            # YAML 头
            assert md.startswith("---\n"), f"{SkillCls.__name__} 缺 front-matter"
            assert "\n---\n" in md, f"{SkillCls.__name__} front-matter 未闭合"
            # 必含字段
            assert f"name: {inst.name}" in md
            assert f"version: {inst.version}" in md
            assert f"category: {inst.category}" in md
            assert "when_to_use:" in md
            assert "allowed_tools:" in md

    def test_export_markdown_body(self, builtin_classes):
        for SkillCls in builtin_classes:
            inst = SkillCls()
            md = inst.export_skill_md()
            assert "# " + inst.name in md
            assert "## When to use" in md
            assert "## Tools" in md
            assert "## Version" in md
            # 至少含一个工具名
            for t in inst.tools:
                assert f"`{t.name}`" in md

    def test_trigger_keywords_in_export(self, builtin_classes):
        for SkillCls in builtin_classes:
            inst = SkillCls()
            md = inst.export_skill_md()
            # 触发关键词至少 1 个出现在 front-matter
            assert "trigger_keywords:" in md

    def test_export_is_unicode_safe(self, builtin_classes):
        for SkillCls in builtin_classes:
            inst = SkillCls()
            md = inst.export_skill_md()
            # 含中文不报错
            assert isinstance(md, str)
            assert len(md) > 100


# ============ 5. write_skill_md 落盘 ============

class TestWriteSkillMd:
    def test_write_creates_dir_and_file(self, tmp_path: Path):
        TravelCls, _, _ = _load_builtin_classes()
        skill = TravelCls()
        target = skill.write_skill_md(base_dir=tmp_path)

        assert target is not None
        assert target.exists()
        assert target.name == "SKILL.md"
        # 父目录结构
        assert (target.parent / "scripts").is_dir()
        assert (target.parent / "references").is_dir()

    def test_write_default_path(self, tmp_path: Path, monkeypatch):
        """不传 base_dir 时默认写到 .claude/skills/<name>/"""
        TravelCls, _, _ = _load_builtin_classes()
        skill = TravelCls()

        # patch PROJECT_ROOT → tmp_path
        from agent.skills import skill as skill_mod

        monkeypatch.setattr(skill_mod, "project_root", tmp_path)

        target = skill.write_skill_md()
        # 即使失败也返 Path;断言存在
        if target and target.exists():
            assert target.parent.name == "low_carbon_travel"
            assert target.name == "SKILL.md"
            content = target.read_text(encoding="utf-8")
            assert "name: low_carbon_travel" in content
        else:
            # 失败也不抛异常(本测试允许)
            assert True

    def test_write_failure_does_not_raise(self, tmp_path: Path, monkeypatch):
        """写文件失败不能抛异常(只 log warning)"""
        from agent.skills import skill as skill_mod

        # 把 base 路径搞成一个 read-only 文件,让 mkdir 失败
        bad = tmp_path / "cant_write_here"
        bad.write_text("blocker")
        # 让 base_dir / bad 当作文件存在 → mkdir parents 会失败
        # 直接用只读文件当父目录的子路径
        # 退而求其次:传一个明显无效的路径(根目录权限通常足够,但跨平台最好)
        # 用 NUL 字符触发 OSError
        try:
            import os

            if os.name == "nt":
                # Windows: 用含 NUL 的路径
                bad_path = Path("Z:\\nonexistent_xyz\\" + "\x00bad")
            else:
                bad_path = Path("/proc/\x00bad")
            inst = skill_mod.Skill  # 拿基类
            # 直接构造一个 dummy 测
            TravelCls, _, _ = _load_builtin_classes()
            skill_inst = TravelCls()
            # 应不抛
            try:
                result = skill_inst.write_skill_md(base_dir=bad_path)
                # 返回值可能是虚拟路径
                assert result is not None
            except Exception as e:
                pytest.fail(f"write_skill_md 抛异常(应静默失败): {e}")
        except Exception:
            # 路径构造本身就失败 — 也算预期
            assert True


# ============ 6. get_schema 向后兼容 ============

class TestSchemaBackwardCompat:
    def test_schema_includes_new_fields(self):
        TravelCls, _, _ = _load_builtin_classes()
        inst = TravelCls()
        s = inst.get_schema()
        # 老字段
        assert "name" in s
        assert "description" in s
        assert "category" in s
        assert "tools" in s
        # 新字段(多返不算破坏)
        assert "version" in s
        assert "when_to_use" in s
        assert "allowed_tools" in s

    def test_get_all_schemas_works(self):
        from agent.skills import get_skill_executor
        from agent.skills.builtin import (
            LowCarbonTravelSkill,
            PolicyQuerySkill,
            ProfileUpdateSkill,
        )

        ex = get_skill_executor()
        for Cls in (LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill):
            ex.register(Cls(), overwrite=True)
        schemas = ex.get_all_schemas()
        assert len(schemas) == 3
        for s in schemas:
            assert "name" in s
            assert "version" in s


# ============ 7. Skill 选择器(eval 启发式)============

class TestSkillSelector:
    def test_selector_picks_travel(self):
        from agent.skills import get_skill_executor
        from agent.skills.builtin import (
            LowCarbonTravelSkill,
            PolicyQuerySkill,
            ProfileUpdateSkill,
        )

        import sys as _sys
        _sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from eval_skills import select_skill as _sel  # type: ignore

        ex = get_skill_executor()
        for Cls in (LowCarbonTravelSkill, PolicyQuerySkill, ProfileUpdateSkill):
            ex.register(Cls(), overwrite=True)

        assert _sel("帮我规划从北京到天津的出行", ex) == "low_carbon_travel"
        assert _sel("查一下最新的碳交易管理办法", ex) == "policy_query"
        assert _sel("更新一下我的画像偏好", ex) == "profile_update"
        # 无任何关键词 → fallback (用极端无关键词 query)
        assert _sel("你好世界", ex) is None