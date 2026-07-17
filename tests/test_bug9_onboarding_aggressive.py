"""
Bug 9 修复测试: onboarding 弹窗不再默认弹出

覆盖:
A. .modal-overlay 默认 display: none(Bug9 修复核心)
B. .modal-overlay.show 才显示
C. showOnboardingModal() 加 .show 类
D. hideOnboardingModal() 删 .show 类
E. DOMContentLoaded 默认调 hideOnboardingModal()
F. 原 7 处 modal.style.display = 'none' 全部替换为 hideOnboardingModal()
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def test_modal_overlay_default_hidden():
    """.modal-overlay 默认 display: none"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 .modal-overlay 块
    m = re.search(r"\.modal-overlay\s*\{([^}]+)\}", content)
    assert m, ".modal-overlay CSS 块未找到"
    body = m.group(1)
    assert "display: none" in body, ".modal-overlay 必须默认 display: none"
    # 不能还有 "display: flex !important" 在默认块里
    assert "display: flex !important" not in body, ".modal-overlay 不应默认 display: flex !important"


def test_modal_overlay_show_class():
    """.modal-overlay.show 才 display: flex"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert ".modal-overlay.show" in content, "必须有 .modal-overlay.show 规则"
    assert "display: flex !important" in content or "display: flex" in content


def test_showOnboardingModal_adds_class():
    """showOnboardingModal() 加 .show class"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    m = re.search(
        r"function showOnboardingModal\(\)\s*\{([^}]+)\}",
        content,
    )
    assert m, "showOnboardingModal 函数未找到"
    body = m.group(1)
    assert "classList.add('show')" in body, "showOnboardingModal 必须 add show class"
    # 不再有 inline display 改动
    assert "modal.style.display" not in body, "showOnboardingModal 不应改 inline style.display"


def test_hideOnboardingModal_removes_class():
    """hideOnboardingModal() 删 .show class"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    m = re.search(
        r"function hideOnboardingModal\(\)\s*\{([^}]+)\}",
        content,
    )
    assert m, "hideOnboardingModal 函数未找到"
    body = m.group(1)
    assert "classList.remove('show')" in body


def test_domcontentloaded_no_longer_shows_modal():
    """DOMContentLoaded 不再自动弹 onboarding"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 DOMContentLoaded 内前 30 行
    m = re.search(
        r"document\.addEventListener\('DOMContentLoaded'[^)]+\)\s*\{([\s\S]+?)\n\s{8}\}\s*\n",
        content,
    )
    assert m, "DOMContentLoaded 块未匹配"
    body = m.group(0)
    # 不再有 "新用户,显示引导模态框" 之类的触发
    assert "新用户,显示引导" not in body
    # 应有 hideOnboardingModal() 默认调用
    assert "hideOnboardingModal()" in body


def test_no_inline_modal_show_calls():
    """不应再有 `modal.style.display = 'flex'`(只允许通过 .show class)"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找所有 modal.style.display
    bad_count = len(re.findall(r"modal\.style\.display\s*=", content))
    assert bad_count == 0, f"仍有 {bad_count} 处 modal.style.display 硬编码,应改用 hideOnboardingModal()"


def test_hideOnboardingModal_called_at_least_once():
    """至少有 1 处 hideOnboardingModal() 调用"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "hideOnboardingModal()" in content
    assert content.count("hideOnboardingModal()") >= 1
