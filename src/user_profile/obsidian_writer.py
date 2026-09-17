"""
P13 Step 5: Obsidian 双向支持 + 路径安全策略

设计:
  · Obsidian Vault 三个子目录,各自有读写权限约束:
      facts/        ← 用户手动(LLM 可读)
      reflection/   ← LLM 写对话摘要(LLM 可读自己写的,但只用于上下文,不计 evidence)
      derived/      ← LLM 推理笔记(LLM 永不再读,防循环)
  · 路径策略:
      - LLM 写:目标路径必须在 derived/ 前缀下,否则抛 PathPolicyViolation
      - LLM 读:严禁读 derived/,否则抛 CircularReadError
  · manifest 记录所有写入,便于审计

API:
  - write_derived_note(uid, name, content) → file path
  - read_reflection_note(uid, name) → content (or None)
  - list_facts(uid) → list of fact file paths
  - safe_path(root, user_path) → 规范化 + 校验
"""
from __future__ import annotations

import json
import logging
import re
import threading
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

_log = logging.getLogger(__name__)

# ============ 异常 ============

class PathPolicyViolation(ValueError):
    """路径违反策略(写到非允许区域 / 读 forbidden 区)"""


class CircularReadError(RuntimeError):
    """LLM 试图读自己写的 derived 笔记 — 防循环"""


# ============ 路径策略 ============

ALLOWED_WRITE_SUBDIRS = {"derived"}  # LLM 只能写到这些子目录
FORBIDDEN_READ_SUBDIRS = {"derived"}  # LLM 不能读这些子目录
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_\-一-鿿\.]{1,80}$")


def _validate_subpath(subpath: str, *, allowed: set, forbidden: set, op: str) -> None:
    """检查 subpath 是否在允许/禁止集合内

    Args:
        subpath:相对 root 的路径(如 "u-xxx/facts/phone.md")
        allowed:允许操作(op='write')的子目录前缀集合
        forbidden:禁止操作(op='read')的子目录前缀集合
        op:'read' or 'write'
    """
    parts = subpath.replace("\\", "/").split("/")
    if len(parts) < 2:
        raise PathPolicyViolation(f"{op}: 路径至少需要 user_alias/file 二段,实际 {subpath!r}")

    if op == "write":
        # 第二段(path[1])必须是 allowed
        sub = parts[1]
        if sub not in allowed:
            raise PathPolicyViolation(
                f"write: 子目录 {sub!r} 不在允许集 {allowed},拒绝写入"
            )
    elif op == "read":
        sub = parts[1]
        if sub in forbidden:
            raise CircularReadError(
                f"read: 子目录 {sub!r} 是 LLM 禁止读取区(防循环),拒绝"
            )


def _validate_safe_name(name: str) -> None:
    if not SAFE_NAME_RE.match(name):
        raise PathPolicyViolation(f"文件名 {name!r} 不符合安全正则 {SAFE_NAME_RE.pattern}")


# ============ Writer ============

class ObsidianWriter:
    """Obsidian 写入器 — 带路径策略

    不修改 obsidian_export.py;独立模块,导出函数供 LLM 调用。
    """

    def __init__(self, vault_root: Path) -> None:
        self.vault_root = Path(vault_root).resolve()
        # 用 RLock(可重入)— 写笔记 + 更新 manifest 是嵌套调用
        self._lock = threading.RLock()
        self._manifest_path = self.vault_root / ".obsidian_writer_manifest.json"

    def _ensure_dirs(self, uid_alias: str, subdir: str) -> Path:
        if subdir not in ALLOWED_WRITE_SUBDIRS:
            raise PathPolicyViolation(f"_ensure_dirs: {subdir!r} 不在写入白名单")
        d = (self.vault_root / uid_alias / subdir).resolve()
        # 防路径逃逸
        if not d.is_relative_to(self.vault_root):
            raise PathPolicyViolation(f"路径逃逸 vault: {d} vs {self.vault_root}")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _resolve(self, uid_alias: str, subdir: str, filename: str) -> Tuple[Path, str]:
        """规范化路径并校验策略"""
        _validate_safe_name(filename)
        rel = f"{uid_alias}/{subdir}/{filename}"
        _validate_subpath(rel, allowed=ALLOWED_WRITE_SUBDIRS, forbidden=set(), op="write")
        d = self._ensure_dirs(uid_alias, subdir)
        full = (d / filename).resolve()
        if not full.is_relative_to(self.vault_root):
            raise PathPolicyViolation(f"路径逃逸 vault: {full}")
        return full, rel

    def _update_manifest(self, op: str, uid_alias: str, rel_path: str) -> None:
        """记录所有写入(便于审计 + 循环检测)"""
        with self._lock:
            manifest = {"version": 1, "writes": [], "reads": []}
            if self._manifest_path.exists():
                try:
                    manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            entry = {
                "op": op,
                "alias": uid_alias,
                "path": rel_path,
                "at": datetime.now(timezone.utc).isoformat(),
            }
            manifest.setdefault(op + "s", []).append(entry)
            # 防 manifest 无限增长
            manifest[op + "s"] = manifest[op + "s"][-500:]
            self._manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # ============ Write API ============

    def write_derived_note(self, uid_alias: str, filename: str,
                            content: str, *, frontmatter_extra: Optional[dict] = None) -> str:
        """写入 LLM 推理笔记到 derived/(LLM 永不再读,防循环)

        Args:
            uid_alias: 用户别名(如 u-<hash24>)
            filename:文件名,不含路径
            content:正文内容
            frontmatter_extra:额外 frontmatter 字段
        Returns:
            相对路径(便于审计)
        """
        full, rel = self._resolve(uid_alias, "derived", filename)
        # 强制 frontmatter 标注 derived
        fm = {
            "profile_alias": uid_alias,
            "generated": True,
            "tags": ["green-profile", "derived"],
            "source": "llm_derived",
            "written_at": datetime.now(timezone.utc).isoformat(),
        }
        if frontmatter_extra:
            fm.update(frontmatter_extra)
        body = "\n".join(["---"] + [f"{k}: {v}" for k, v in fm.items()] + ["---", "", content])
        with self._lock:
            full.write_text(body, encoding="utf-8")
            self._update_manifest("write", uid_alias, rel)
        _log.info("[obsidian_writer] wrote derived note: %s", rel)
        return rel

    # ============ Read API(只读 reflection + facts,严禁 derived) ============

    def read_note(self, uid_alias: str, subdir: str, filename: str) -> Optional[str]:
        """读 reflection 或 facts 下的笔记(严禁 derived)

        Raises:
            CircularReadError: 当 subdir=='derived'
        """
        if subdir in FORBIDDEN_READ_SUBDIRS:
            raise CircularReadError(
                f"read_note: 子目录 {subdir!r} 是 LLM 禁止读取区(防循环)"
            )
        _validate_safe_name(filename)
        rel = f"{uid_alias}/{subdir}/{filename}"
        _validate_subpath(rel, allowed=set(), forbidden=FORBIDDEN_READ_SUBDIRS, op="read")
        d = self.vault_root / uid_alias / subdir
        full = (d / filename).resolve()
        if not full.is_relative_to(self.vault_root):
            raise PathPolicyViolation(f"read_note: 路径逃逸 vault: {full}")
        if not full.exists():
            return None
        with self._lock:
            self._update_manifest("read", uid_alias, rel)
        return full.read_text(encoding="utf-8")

    def list_user_files(self, uid_alias: str, subdir: str) -> List[str]:
        """列某用户在指定子目录的文件(只能列非 forbidden 区)"""
        if subdir in FORBIDDEN_READ_SUBDIRS:
            raise CircularReadError(
                f"list_user_files: 子目录 {subdir!r} 是 LLM 禁止读取区(防循环)"
            )
        d = self.vault_root / uid_alias / subdir
        if not d.exists():
            return []
        return sorted([p.name for p in d.iterdir() if p.is_file()])


# ============ alias 工具(与 obsidian_export.py 一致) ============

def make_user_alias(user_id: str) -> str:
    """生成用户别名(24 hex),与 obsidian_export 内部一致"""
    import hashlib
    return "u-" + hashlib.sha256(str(user_id).encode("utf-8")).hexdigest()[:24]


__all__ = [
    "ObsidianWriter",
    "PathPolicyViolation",
    "CircularReadError",
    "ALLOWED_WRITE_SUBDIRS",
    "FORBIDDEN_READ_SUBDIRS",
    "make_user_alias",
]