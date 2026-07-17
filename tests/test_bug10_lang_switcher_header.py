"""
Bug 10 修复测试: 中英文/设置按钮移到 header 内联

覆盖:
A. .api-key-btn 不再 position: fixed(已改为 inline-flex)
B. .top-right-actions 容器存在,内含 .api-key-btn
C. i18n.js 注入 lang-switcher 到 .top-right-actions 优先,fallback 到 body
D. 旧的 document.body.appendChild 注入路径被替换
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ---------------------------------------------------------------------------
# A. .api-key-btn 不再 fixed
# ---------------------------------------------------------------------------
def test_api_key_btn_not_fixed():
    """.api-key-btn 必须不再 position: fixed"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    m = re.search(r"\.api-key-btn\s*\{([^}]+)\}", content)
    assert m, ".api-key-btn 块未找到"
    body = m.group(1)
    # 不应有 position: fixed
    assert "position: fixed" not in body and "position:fixed" not in body, (
        ".api-key-btn 不应 position: fixed(已改为 inline-flex)"
    )
    # 应有 display: inline-flex
    assert "display: inline-flex" in body, ".api-key-btn 应为 inline-flex"


def test_api_key_btn_in_header_top_right_actions():
    """api-key-btn 必须在 .top-right-actions 内联"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # 找 .top-right-actions 块
    m = re.search(
        r'<div class="top-right-actions">([\s\S]+?)</div>',
        content,
    )
    assert m, ".top-right-actions 块未找到"
    body = m.group(1)
    assert "api-key-btn" in body, ".top-right-actions 必须含 .api-key-btn"
    assert "showApiKeyModal()" in body


def test_old_fixed_api_key_btn_removed():
    """原 .api-key-btn 独立 fixed 按钮已删"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    # Bug10 注释应有: "已移入 .top-right-actions"(带或不带 .header 都行)
    assert ("API Key 设置按钮已移入 .top-right-actions" in content
            or "API Key 设置按钮已移入 .header .top-right-actions" in content)
    # 应有 1 个 .api-key-btn(在 header 内)
    # 用 [\s\S] 跨行匹配
    fixed_buttons = re.findall(
        r'<button[\s\S]*?class="api-key-btn"[\s\S]*?>',
        content,
    )
    assert len(fixed_buttons) == 1, f"应有 1 个 .api-key-btn,实际 {len(fixed_buttons)}"


# ---------------------------------------------------------------------------
# B. .top-right-actions 容器
# ---------------------------------------------------------------------------
def test_top_right_actions_styled():
    """.top-right-actions 必须有 flex 布局"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    m = re.search(r"\.top-right-actions\s*\{([^}]+)\}", content)
    assert m
    body = m.group(1)
    assert "display: flex" in body
    assert "align-items: center" in body
    assert "gap: 8px" in body or "gap:8px" in body


def test_top_right_actions_lang_switcher_overrides():
    """i18n.js 注入的 #lang-switcher 需被 .top-right-actions 内的 CSS 覆盖 fixed"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "#lang-switcher" in content
    # 应有 .top-right-actions #lang-switcher 规则
    assert ".top-right-actions #lang-switcher" in content, (
        "必须有 .top-right-actions #lang-switcher 规则覆盖 fixed 定位"
    )
    assert "position: static" in content, "覆盖规则必须有 position: static"


# ---------------------------------------------------------------------------
# C. i18n.js 优先注入到 .top-right-actions
# ---------------------------------------------------------------------------
def test_i18n_js_injects_to_top_right_actions():
    """i18n.js 必须把 lang-switcher 注入到 .top-right-actions 容器"""
    i18n = (PROJECT_ROOT / "web/i18n.js").read_text(encoding="utf-8")
    # 必须有 top-right-actions 关键字
    assert "top-right-actions" in i18n, "i18n.js 必须支持 .top-right-actions 注入"
    # 必须有 insertBefore(在设置按钮之前)
    assert "insertBefore" in i18n, "i18n.js 必须用 insertBefore 把切换器放在设置按钮之前"
    # 必须有 fallback 路径(fixed 注入)
    assert "position:fixed" in i18n or "position: fixed" in i18n, "i18n.js 必须保留 fallback fixed 注入"


def test_i18n_js_syntax_valid():
    """i18n.js 语法检查"""
    js_path = PROJECT_ROOT / "web/i18n.js"
    proc = subprocess.run(
        ["node", "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"i18n.js 语法错误:{proc.stderr[:500]}"


# ---------------------------------------------------------------------------
# D. 旧 fixed api-key-btn 注释
# ---------------------------------------------------------------------------
def test_old_button_replaced_comment():
    """必须有 Bug10 注释说明旧按钮已移走"""
    content = (PROJECT_ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "Bug10" in content
    assert ".top-right-actions" in content
