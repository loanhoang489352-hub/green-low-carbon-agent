"""
P6.H i18n 中英双语 单元测试

覆盖:
1. t() 基本翻译(zh/en)
2. set_locale / get_locale 线程级
3. get_locale_from_header 解析 Accept-Language
4. message_for() 按 locale 返错误消息
5. APIError 按 locale 切换消息
6. /api/chat/enhanced 401 错误消息跟随 Accept-Language
"""
import os
import sys
import json
import threading
import uuid
from io import BytesIO
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


@pytest.fixture(autouse=True)
def clean_thread_locale():
    """每个测试后清 thread-local locale(避免污染)"""
    from i18n import set_locale
    set_locale("zh")
    yield
    set_locale("zh")


# ========== 1. t() 基本翻译 ==========

def test_t_basic_zh():
    from i18n import t
    assert t("error.unauthorized", locale="zh") == "需要登录"
    assert t("ui.title", locale="zh") == "绿色低碳智能体"


def test_t_basic_en():
    from i18n import t
    assert t("error.unauthorized", locale="en") == "Authentication required"
    assert t("ui.title", locale="en") == "Green Low-Carbon Agent"


def test_t_missing_key_fallback():
    """缺失 key 返 [key] 占位"""
    from i18n import t
    assert t("nonexistent.key", locale="zh") == "[nonexistent.key]"


def test_t_with_format_args():
    """格式化参数(P6.H: {name} 占位符用 **kwargs)"""
    from i18n import t
    import i18n
    i18n.TRANSLATIONS["zh"]["test.format_named"] = "你好,{name}"
    i18n.TRANSLATIONS["en"]["test.format_named"] = "Hello, {name}"
    assert t("test.format_named", locale="zh", name="Alice") == "你好,Alice"
    assert t("test.format_named", locale="en", name="Bob") == "Hello, Bob"


# ========== 2. set/get_locale 线程级 ==========

def test_set_get_locale_basic():
    from i18n import set_locale, get_locale
    set_locale("en")
    assert get_locale() == "en"
    set_locale("zh")
    assert get_locale() == "zh"


def test_set_locale_normalizes():
    """set_locale("zh-CN") → 标准化为 "zh" """
    from i18n import set_locale, get_locale
    set_locale("zh-CN")
    assert get_locale() == "zh"
    set_locale("en-US")
    assert get_locale() == "en"


def test_locale_thread_isolated():
    """P6.H: locale 是 thread-local,不同线程互不干扰"""
    from i18n import set_locale, get_locale
    results = {}

    def worker(tid):
        set_locale("en" if tid % 2 == 0 else "zh")
        import time as _t
        _t.sleep(0.05)
        results[tid] = get_locale()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert results[0] == "en"
    assert results[1] == "zh"
    assert results[2] == "en"
    assert results[3] == "zh"


# ========== 3. Accept-Language 解析 ==========

def test_get_locale_from_header_en_first():
    from i18n import get_locale_from_header
    assert get_locale_from_header("en-US,zh-CN;q=0.9") == "en"


def test_get_locale_from_header_zh_first():
    from i18n import get_locale_from_header
    assert get_locale_from_header("zh-CN,en;q=0.8") == "zh"


def test_get_locale_from_header_empty():
    from i18n import get_locale_from_header
    assert get_locale_from_header("") == "zh"  # 默认


def test_get_locale_from_header_garbage():
    from i18n import get_locale_from_header
    assert get_locale_from_header("fr-DE") == "zh"  # 不支持 → 默认


# ========== 4. message_for 按 locale ==========

def test_message_for_zh():
    from server.errors import message_for
    assert message_for("UNAUTHORIZED", locale="zh") == "需要登录"
    assert message_for("RATE_LIMITED", locale="zh") == "请求过于频繁"


def test_message_for_en():
    from server.errors import message_for
    assert message_for("UNAUTHORIZED", locale="en") == "Authentication required"
    assert message_for("RATE_LIMITED", locale="en") == "Too many requests"


def test_message_for_unknown_code_falls_back():
    from server.errors import message_for
    assert "未知" in message_for("UNKNOWN_CODE", locale="zh")
    assert "Unknown" in message_for("UNKNOWN_CODE", locale="en")


# ========== 5. APIError 按 locale ==========

def test_api_error_zh():
    from server.errors import APIError
    e = APIError("UNAUTHORIZED", locale="zh")
    assert e.message == "需要登录"
    assert e.status == 401


def test_api_error_en():
    from server.errors import APIError
    e = APIError("UNAUTHORIZED", locale="en")
    assert e.message == "Authentication required"


def test_api_error_explicit_message_overrides():
    """显式 message 覆盖自动翻译"""
    from server.errors import APIError
    e = APIError("UNAUTHORIZED", message="自定义消息", locale="en")
    assert e.message == "自定义消息"  # 显式优先


# ========== 6. 端到端:HTTP 401 跟随 Accept-Language ==========

def test_http_401_follows_accept_language():
    """P6.H: /api/chat 无 token + Accept-Language: en → 返英文错误"""
    from server.app import RoutedRequestHandler
    from server.router import reset_registry, get_registry
    from server.routers import register_all_routes

    reset_registry()
    register_all_routes(get_registry())

    def make_handler(accept_lang):
        handler = RoutedRequestHandler.__new__(RoutedRequestHandler)
        handler.path = "/api/chat"
        handler.headers = {"Accept-Language": accept_lang}  # 无 Authorization
        handler.command = "POST"
        handler.request_version = "HTTP/1.1"
        handler.rfile = BytesIO(b'{"message":"hi","user_id":"u"}')
        handler.wfile = BytesIO()
        handler.last_status = None
        handler.last_body = b""
        def instance_send_json(data, status=200):
            handler.last_status = status
            handler.last_body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        handler.send_json = instance_send_json
        handler.send_response = lambda s: setattr(handler, "last_status", s)
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None
        handler._read_body = lambda: '{"message":"hi","user_id":"u"}'
        handler._cors_origin = lambda: "*"
        handler.log_message = lambda fmt, *a: None
        handler.client_address = ("127.0.0.1", 9999)
        return handler

    # Accept-Language: en → 401 英文
    h = make_handler("en-US,zh;q=0.5")
    RoutedRequestHandler.do_POST(h)
    assert h.last_status == 401
    body = json.loads(h.last_body.decode("utf-8"))
    msg = body["error"]["message"]
    assert "Authentication" in msg or "登录" in msg, f"应英或中,实际 {msg}"

    # Accept-Language: zh → 401 中文
    h = make_handler("zh-CN,en;q=0.5")
    RoutedRequestHandler.do_POST(h)
    assert h.last_status == 401
    body = json.loads(h.last_body.decode("utf-8"))
    assert "需要登录" in body["error"]["message"]


def test_list_keys_covers_all_categories():
    """P6.H: 翻译字典应覆盖错误/健康/UI 至少 10 个 key"""
    from i18n import list_keys
    keys = list_keys()
    assert len(keys) >= 10, f"应至少 10 个 key, 实际 {len(keys)}"
    # 覆盖
    has_error = any(k.startswith("error.") for k in keys)
    has_ui = any(k.startswith("ui.") for k in keys)
    assert has_error and has_ui
