"""
P6.S.23: 前端 XSS 转义 + 事件委托回归测试

由于 web/index.html 是单体内嵌 JS,无法直接 import,这里采用
正则 + 静态扫描方式验证关键 XSS 修复点 + 事件委托存在。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
INDEX_HTML = PROJECT_ROOT / "web" / "index.html"


def _read_index():
    return INDEX_HTML.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. escapeHtml 工具函数存在
# ---------------------------------------------------------------------------
def test_escapeHtml_function_exists():
    content = _read_index()
    assert "function escapeHtml" in content, "escapeHtml 函数必须存在"
    # 抓整个函数体(到下一个独立 function 定义)
    start = content.find("function escapeHtml(s)")
    assert start > 0
    # 截取到下一个 "function " 关键字之前
    next_fn = content.find("function ", start + 30)
    body = content[start:next_fn] if next_fn > 0 else content[start:start+1500]
    for ch in ["&amp;", "&lt;", "&gt;", "&quot;", "&#39;"]:
        assert ch in body, f"escapeHtml 漏转义 {ch}"


def test_createUserId_function_exists():
    content = _read_index()
    assert "function createUserId" in content
    # 必须用 crypto.randomUUID
    m = re.search(r"function createUserId[\s\S]+?return\s+`", content)
    assert m
    assert "crypto" in m.group(0) or "randomUUID" in m.group(0)


# ---------------------------------------------------------------------------
# 2. Math.random().substr 已废弃,必须没有新残留
# ---------------------------------------------------------------------------
def test_no_more_math_random_substr():
    content = _read_index()
    # 排除注释行(以 // 或 /* 开头)。5 处旧代码已替换,只剩 1 处 P6.S.23 注释提到。
    lines = content.split("\n")
    code_lines = [ln for ln in lines if not ln.strip().startswith("//") and not ln.strip().startswith("*")]
    code_only = "\n".join(code_lines)
    matches = re.findall(r"Math\.random\(\)\.toString\(36\)\.substr\(", code_only)
    assert len(matches) == 0, f"Math.random().substr() 在代码中仍有 {len(matches)} 处残留"


# ---------------------------------------------------------------------------
# 3. addMessage 必须用 escapeHtml 转义 user/后端可控字段
# ---------------------------------------------------------------------------
def test_addMessage_uses_escapeHtml():
    content = _read_index()
    # 找 addMessage 函数
    m = re.search(r"function addMessage[\s\S]+?container\.appendChild", content)
    assert m, "addMessage 函数未找到"
    body = m.group(0)
    # 关键 XSS 点:recommendation.action / category / examples / suggestion / knowledgeRefs
    assert "${escapeHtml(r.action)}" in body, "r.action 必须转义"
    assert "${escapeHtml(r.category" in body, "r.category 必须转义"
    assert "${escapeHtml(s)}" in body or "data-suggestion=\"${escapeHtml(s)}" in body, "suggestion 必须转义或用 data 属性"
    # knowledgeRefs 也要转义
    assert "escapeHtml(knowledgeRefs" in body or "knowledgeRefs.map" in body, "knowledgeRefs 应转义"


def test_suggestion_uses_event_delegation():
    """suggestion 按钮 onclick 拼接必须改为事件委托 + data-suggestion"""
    content = _read_index()
    # 旧的 onclick 拼接模式不应再出现
    bad_pattern = re.findall(
        r"onclick=\"sendQuickMessage\('\$\{s\.replace\(/" , content
    )
    assert len(bad_pattern) == 0, f"旧 suggestion 拼接 onclick 还有 {len(bad_pattern)} 处"


# ---------------------------------------------------------------------------
# 4. sendMessage 入口有 loading + 防双击
# ---------------------------------------------------------------------------
def test_sendMessage_has_loading():
    content = _read_index()
    m = re.search(r"async function sendMessage[\s\S]+?_isSending = false;", content)
    assert m, "sendMessage 必须有 _isSending 防双击"
    assert "setSendButtonLoading" in m.group(0), "必须调 setSendButtonLoading"


def test_setSendButtonLoading_exists():
    content = _read_index()
    m = re.search(r"function setSendButtonLoading[\s\S]+?sendBtn\.innerHTML = '➤';", content)
    assert m, "setSendButtonLoading 必须存在"
    assert "spinner" in m.group(0).lower(), "loading 必须有 spinner"


def test_sendMessage_has_retry_button():
    content = _read_index()
    # 找 sendMessage 函数体内的 catch 块(第 2 个 catch (error) 出现位置)
    # 因为 onboarding 等也有 catch (error)
    send_fn_idx = content.find("async function sendMessage")
    assert send_fn_idx > 0
    catch_idx = content.find("catch (error)", send_fn_idx)
    assert catch_idx > 0, "sendMessage 函数体内必须有 catch (error) 块"
    snippet = content[catch_idx:catch_idx + 2500]
    assert "retry-btn" in snippet, "sendMessage 的 catch 块必须生成重试按钮"
    assert "data-retry" in snippet, "重试按钮必须有 data-retry 属性供事件委托"


# ---------------------------------------------------------------------------
# 5. formatContent 先转义再标记化
# ---------------------------------------------------------------------------
def test_formatContent_escapes_first():
    content = _read_index()
    start = content.find("function formatContent")
    assert start > 0
    next_fn = content.find("function ", start + 30)
    body = content[start:next_fn] if next_fn > 0 else content[start:start+1500]
    assert "escapeHtml(String(content))" in body, "formatContent 必须先 escapeHtml"
    assert ".replace" in body, "formatContent 必须有 markdown replace"
    escaped_idx = body.find("escapeHtml")
    replace_idx = body.find(".replace")
    assert escaped_idx > 0 and replace_idx > escaped_idx, f"escapeHtml({escaped_idx}) 必须在 .replace({replace_idx}) 之前"


# ---------------------------------------------------------------------------
# 6. loadKnowledgeStats 用 RAG 数字
# ---------------------------------------------------------------------------
def test_loadKnowledgeStats_uses_rag():
    content = _read_index()
    m = re.search(r"async function loadKnowledgeStats[\s\S]+?\}", content)
    assert m
    body = m.group(0)
    assert "rag_stats" in body, "loadKnowledgeStats 必须消费 rag_stats"
    assert "vector_store_count" in body, "loadKnowledgeStats 必须用 vector_store_count"


# ---------------------------------------------------------------------------
# 7. 事件委托总入口
# ---------------------------------------------------------------------------
def test_chat_container_delegation_exists():
    content = _read_index()
    assert "setupChatContainerDelegation" in content
    # 委托 click listener 处理 suggestion / feedback / retry
    m = re.search(
        r"container\.addEventListener\('click'[\s\S]+?reason-submit-btn'\)",
        content,
    )
    assert m, "chat-container click 委托必须处理 4 类按钮"


# ---------------------------------------------------------------------------
# 8. 出行卡片占位渲染
# ---------------------------------------------------------------------------
def test_travel_card_render_exists():
    content = _read_index()
    start = content.find("function addMessage(")
    assert start > 0
    next_fn = content.find("function formatContent", start + 30)
    body = content[start:next_fn] if next_fn > 0 else content[start:start+10000]
    assert "toolResult" in body, "addMessage 必须接收 toolResult 参数"
    assert "toolResult && toolResult.routes" in body, "addMessage 必须检查 toolResult.routes"
    assert "travel-card" in body, "必须渲染 travel-card div"
    assert "travel-route" in body, "必须渲染路线子项"


# ---------------------------------------------------------------------------
# 9. location 标签
# ---------------------------------------------------------------------------
def test_location_tag_render():
    content = _read_index()
    assert "location-tag" in content
    assert "location.city" in content


# ---------------------------------------------------------------------------
# 10. CSS: 出行卡片 / 重试按钮 / 移动端适配
# ---------------------------------------------------------------------------
def test_css_travel_card_exists():
    content = _read_index()
    assert ".travel-card" in content
    assert ".travel-route" in content
    assert ".retry-btn" in content
    assert "@media (max-width: 600px)" in content
    assert "@media (hover: none)" in content
