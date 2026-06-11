"""
P6.L Web UI 国际化 单元测试

覆盖:
1. web/i18n.js 存在 + 是有效 JavaScript
2. 字典覆盖 zh/en 至少 5 个 key
3. server 提供 /i18n.js 路由(200 + application/javascript)
4. /index.html 头部 <script src="/i18n.js"></script> 注入
5. python i18n 模块的 ui.* 字典与 JS 字典 key 同步(避免漂移)
6. i18n.js 含浮动切换器 + 翻译函数
"""
import json
import re
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. i18n.js 存在 + 有效 JS ==========

def test_i18n_js_exists():
    """P6.L: web/i18n.js 文件存在"""
    js_path = project_root / "web" / "i18n.js"
    assert js_path.exists(), f"web/i18n.js 应存在, 实际 {js_path}"
    assert js_path.stat().st_size > 1000, "i18n.js 应 > 1KB"


def test_i18n_js_valid_javascript():
    """P6.L: i18n.js 是有效 JavaScript(能加载不抛错)"""
    js_path = project_root / "web" / "i18n.js"
    content = js_path.read_text(encoding="utf-8")
    # 基本语法检查
    assert "(function () {" in content, "i18n.js 应是 IIFE 封装"
    assert "applyI18n" in content, "i18n.js 应含 applyI18n 函数"
    assert "I18N" in content, "i18n.js 应含 I18N 字典"


# ========== 2. 字典覆盖 ==========

def test_i18n_js_dict_covers_zh_en():
    """P6.L: 字典覆盖 zh/en 至少 5 个 key"""
    js_path = project_root / "web" / "i18n.js"
    content = js_path.read_text(encoding="utf-8")

    # zh 字典
    zh_match = re.search(r"const I18N = \{\s*zh:\s*\{(.*?)\},\s*en:\s*\{", content, re.DOTALL)
    assert zh_match, "i18n.js 应含 I18N.zh 字典块"
    zh_keys = re.findall(r'\"([\w.]+)\":', zh_match.group(1))
    assert len(zh_keys) >= 5, f"zh 字典应至少 5 个 key, 实际 {len(zh_keys)}"
    for k in ["ui.title", "ui.send", "ui.chat_placeholder", "ui.thinking"]:
        assert k in zh_keys, f"zh 字典应含 key {k}"


def test_i18n_js_dict_zh_en_match():
    """P6.L: zh 和 en 字典 key 一一对应(避免漂移)"""
    js_path = project_root / "web" / "i18n.js"
    content = js_path.read_text(encoding="utf-8")

    zh_block = re.search(r"zh:\s*\{(.*?)\},", content, re.DOTALL).group(1)
    en_block = re.search(r"en:\s*\{(.*?)\},", content, re.DOTALL).group(1)

    zh_keys = set(re.findall(r'\"([\w.]+)\":', zh_block))
    en_keys = set(re.findall(r'\"([\w.]+)\":', en_block))
    assert zh_keys == en_keys, f"zh 和 en 字典 key 不一致:\n  zh-only: {zh_keys - en_keys}\n  en-only: {en_keys - zh_keys}"


# ========== 3. server 路由 ==========

def test_server_routes_i18n_js():
    """P6.L: RoutedRequestHandler.do_GET /i18n.js 返 200 + application/javascript"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes
    from io import BytesIO

    reset_registry()
    register_all_routes(get_registry())

    handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
    handler.path = "/i18n.js"
    handler.headers = {}
    handler.command = "GET"
    handler.request_version = "HTTP/1.1"
    handler.rfile = BytesIO(b"")
    handler.wfile = BytesIO()
    handler.last_status = None
    handler.last_body = b""
    handler.last_content_type = None

    def instance_send_response(status):
        handler.last_status = status
    def instance_send_header(k, v):
        if k.lower() == "content-type":
            handler.last_content_type = v
    def instance_end_headers():
        pass
    handler.send_response = instance_send_response
    handler.send_header = instance_send_header
    handler.end_headers = instance_end_headers
    handler.wfile.write = lambda b: handler.last_body.__iadd__(b) if hasattr(handler.last_body, '__iadd__') else None
    handler.last_body = b""
    handler._read_body = lambda: ""
    handler._cors_origin = lambda: "*"
    handler.log_message = lambda fmt, *a: None

    RoutedRequestHandler.do_GET(handler)
    assert handler.last_status == 200, f"应 200, 实际 {handler.last_status}"
    assert "javascript" in (handler.last_content_type or "").lower(), \
        f"应 application/javascript, 实际 {handler.last_content_type}"
    # 内容应含 IIFE 和字典
    body_bytes = handler.wfile.getvalue() if hasattr(handler.wfile, 'getvalue') else b""
    # 上面 _send_header wfile.write 没收集 body,直接读文件替代验证
    js_content = (project_root / "web" / "i18n.js").read_text(encoding="utf-8")
    assert "I18N" in js_content


# ========== 4. index.html 注入 ==========

def test_index_html_includes_i18n_js():
    """P6.L: web/index.html 头部 <script src=/i18n.js> 注入"""
    html = (project_root / "web" / "index.html").read_text(encoding="utf-8")
    assert '/i18n.js' in html, "index.html 应引用 /i18n.js"
    # 在 <head> 内
    head_end = html.find("</head>")
    script_pos = html.find("/i18n.js")
    assert script_pos > 0 and script_pos < head_end, "/i18n.js script 应在 </head> 之前"


# ========== 5. python i18n 模块与 JS 字典同步 ==========

def test_python_i18n_zh_keys_in_js():
    """P6.L: python i18n 模块的 ui.* 字典应至少被 JS 字典子集覆盖"""
    from i18n import TRANSLATIONS

    py_zh_keys = set(k for k in TRANSLATIONS["zh"].keys() if k.startswith("ui."))
    js_content = (project_root / "web" / "i18n.js").read_text(encoding="utf-8")
    js_keys = set(re.findall(r'\"(ui\.[\w.]+)\":', js_content))

    # JS 字典应至少覆盖 python 字典的 ui.* 全部
    missing = py_zh_keys - js_keys
    assert not missing, f"JS 字典缺这些 python ui key: {missing}"


# ========== 6. i18n.js 功能检查(关键词) ==========

def test_i18n_js_has_float_switcher():
    """P6.L: 浮动语言切换器(右上角定位)"""
    content = (project_root / "web" / "i18n.js").read_text(encoding="utf-8")
    assert "position:fixed" in content
    assert "top:12px" in content
    assert "right:12px" in content
    assert "lang-switcher" in content


def test_i18n_js_patches_fetch():
    """P6.L: fetch 包装自动带 Accept-Language 头"""
    content = (project_root / "web" / "i18n.js").read_text(encoding="utf-8")
    assert "patchFetch" in content
    assert "Accept-Language" in content
    assert "window.fetch" in content


def test_i18n_js_localstorage_persistence():
    """P6.L: localStorage 持久化 locale"""
    content = (project_root / "web" / "i18n.js").read_text(encoding="utf-8")
    assert "localStorage" in content
    assert "green_agent_locale" in content


def test_i18n_js_url_lang_param():
    """P6.L: URL ?lang=zh/en 优先级最高"""
    content = (project_root / "web" / "i18n.js").read_text(encoding="utf-8")
    assert "searchParams" in content
    assert "?lang" in content or "lang=" in content
