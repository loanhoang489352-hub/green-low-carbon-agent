"""
Step 5 验收测试:Obsidian 双向分层(20 个测试)

覆盖:
  · 路径策略白名单/黑名单(5)
  · 写入 derived/(3)
  · 写入非法子目录抛错(3)
  · 读 derived/ 抛 CircularReadError(2)
  · 读 reflection/facts 正常(2)
  · 文件名安全正则(2)
  · alias 工具 + manifest(3)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from user_profile.obsidian_writer import (
    ObsidianWriter,
    PathPolicyViolation,
    CircularReadError,
    ALLOWED_WRITE_SUBDIRS,
    FORBIDDEN_READ_SUBDIRS,
    make_user_alias,
    _validate_subpath,
    _validate_safe_name,
)


@pytest.fixture
def vault(tmp_path):
    """临时 vault"""
    return tmp_path / "vault"


# ============ 1. 路径策略白/黑名单(5) ============

class TestPathPolicy:
    def test_write_derived_allowed(self):
        _validate_subpath("u-abc/derived/note.md",
                         allowed=ALLOWED_WRITE_SUBDIRS, forbidden=set(), op="write")

    def test_write_to_facts_rejected(self):
        with pytest.raises(PathPolicyViolation, match="不在允许集"):
            _validate_subpath("u-abc/facts/note.md",
                            allowed=ALLOWED_WRITE_SUBDIRS, forbidden=set(), op="write")

    def test_write_to_reflection_rejected(self):
        with pytest.raises(PathPolicyViolation):
            _validate_subpath("u-abc/reflection/note.md",
                            allowed=ALLOWED_WRITE_SUBDIRS, forbidden=set(), op="write")

    def test_read_derived_rejected(self):
        with pytest.raises(CircularReadError, match="禁止读取区"):
            _validate_subpath("u-abc/derived/note.md",
                            allowed=set(), forbidden=FORBIDDEN_READ_SUBDIRS, op="read")

    def test_read_facts_allowed(self):
        _validate_subpath("u-abc/facts/note.md",
                         allowed=set(), forbidden=FORBIDDEN_READ_SUBDIRS, op="read")


# ============ 2. 写入 derived/(3) ============

class TestWriteDerived:
    def test_write_basic(self, vault):
        w = ObsidianWriter(vault)
        alias = "u-aaaa"
        rel = w.write_derived_note(alias, "note1.md", "推理内容")
        assert rel == "u-aaaa/derived/note1.md"
        assert (vault / alias / "derived" / "note1.md").exists()

    def test_write_with_frontmatter(self, vault):
        w = ObsidianWriter(vault)
        rel = w.write_derived_note("u-aaaa", "note.md", "content",
                                    frontmatter_extra={"plan_id": "plan-1"})
        body = (vault / "u-aaaa" / "derived" / "note.md").read_text(encoding="utf-8")
        assert "profile_alias: u-aaaa" in body
        assert "source: llm_derived" in body
        assert "plan_id: plan-1" in body
        assert "content" in body

    def test_write_creates_dirs(self, vault):
        w = ObsidianWriter(vault)
        w.write_derived_note("u-bbbb", "x.md", "hi")
        assert (vault / "u-bbbb" / "derived").is_dir()


# ============ 3. 非法子目录抛错(3) ============

class TestWritePolicyViolation:
    def test_write_to_facts_raises(self, vault):
        w = ObsidianWriter(vault)
        with pytest.raises(PathPolicyViolation):
            # 强制调用:绕过公共 API 的内部防御
            w._resolve("u-aaaa", "facts", "x.md")

    def test_write_to_reflection_raises(self, vault):
        w = ObsidianWriter(vault)
        with pytest.raises(PathPolicyViolation):
            w._resolve("u-aaaa", "reflection", "x.md")

    def test_write_to_root_raises(self, vault):
        w = ObsidianWriter(vault)
        with pytest.raises(PathPolicyViolation):
            w._resolve("u-aaaa", ".", "x.md")


# ============ 4. 读 derived/ 抛 CircularReadError(2) ============

class TestCircularReadPrevention:
    def test_read_derived_raises(self, vault):
        # 先写一份 derived
        w = ObsidianWriter(vault)
        w.write_derived_note("u-aaaa", "internal.md", "secret")
        # 再读 → 必须抛错
        with pytest.raises(CircularReadError):
            w.read_note("u-aaaa", "derived", "internal.md")

    def test_list_derived_raises(self, vault):
        w = ObsidianWriter(vault)
        w.write_derived_note("u-aaaa", "x.md", "hi")
        with pytest.raises(CircularReadError):
            w.list_user_files("u-aaaa", "derived")


# ============ 5. 读 reflection/facts 正常(2) ============

class TestReadAllowed:
    def test_read_reflection(self, vault):
        w = ObsidianWriter(vault)
        # reflection 目录手动建(此模块不负责写 reflection,但可读)
        d = vault / "u-aaaa" / "reflection"
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.md").write_text("# 摘要\n", encoding="utf-8")
        body = w.read_note("u-aaaa", "reflection", "summary.md")
        assert body == "# 摘要\n"

    def test_read_nonexistent_returns_none(self, vault):
        w = ObsidianWriter(vault)
        body = w.read_note("u-aaaa", "reflection", "missing.md")
        assert body is None


# ============ 6. 文件名安全正则(2) ============

class TestSafeName:
    def test_safe_name_accepts(self):
        _validate_safe_name("note1.md")
        _validate_safe_name("2024-01-15.md")
        _validate_safe_name("节能笔记.md")
        _validate_safe_name("plan_abc-v2.md")

    def test_unsafe_name_rejects(self):
        with pytest.raises(PathPolicyViolation):
            _validate_safe_name("../escape.md")
        with pytest.raises(PathPolicyViolation):
            _validate_safe_name("note/with/slash.md")
        with pytest.raises(PathPolicyViolation):
            _validate_safe_name("")  # 空字符串
        with pytest.raises(PathPolicyViolation):
            _validate_safe_name("name with space.md")  # 空格


# ============ 7. alias + manifest(3) ============

class TestAliasAndManifest:
    def test_alias_consistent(self):
        a1 = make_user_alias("user-123")
        a2 = make_user_alias("user-123")
        assert a1 == a2
        assert a1.startswith("u-")
        assert len(a1) == 2 + 24  # u- + 24 hex

    def test_alias_different(self):
        a1 = make_user_alias("user-1")
        a2 = make_user_alias("user-2")
        assert a1 != a2

    def test_manifest_records_writes(self, vault):
        w = ObsidianWriter(vault)
        w.write_derived_note("u-aaaa", "n1.md", "x")
        w.write_derived_note("u-aaaa", "n2.md", "y")
        manifest_path = vault / ".obsidian_writer_manifest.json"
        assert manifest_path.exists()
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        writes = m["writes"]
        assert len(writes) == 2
        assert all(w["op"] == "write" for w in writes)
        assert all("derived/n" in w["path"] for w in writes)

    def test_manifest_records_reads(self, vault):
        w = ObsidianWriter(vault)
        d = vault / "u-aaaa" / "reflection"
        d.mkdir(parents=True, exist_ok=True)
        (d / "s.md").write_text("hi", encoding="utf-8")
        w.read_note("u-aaaa", "reflection", "s.md")
        m = json.loads((vault / ".obsidian_writer_manifest.json").read_text(encoding="utf-8"))
        assert len(m["reads"]) == 1