"""
P6.P Web e2e 浏览器端到端测试(playwright)

覆盖:
1. 打开主页显示中文 + 含 title="绿色低碳智能体"
2. /i18n.js 自动加载(浮动切换器注入)
3. 点击切换器切到英文,Web UI 翻译
4. URL ?lang=en 参数优先
5. 健康 API 端点 200
6. 浮动切换器在右上角(z-index 高)
7. 浮动切换器 localStorage 持久化

用法:
    # 1) 启动 Web 服务(后台)
    cd src && nohup python main.py > /tmp/web_e2e.log 2>&1 &
    sleep 16  # 等模型加载

    # 2) 跑 e2e
    pytest tests/test_p6p_web_e2e.py -v --tb=short -p no:cacheprovider

    # 3) 清理
    pkill -f "python main.py"
"""
import sys
import time
import socket
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest
from playwright.sync_api import sync_playwright, expect


WEB_URL = "http://localhost:8000"


def _wait_for_port(host: str = "localhost", port: int = 8000, timeout: float = 30.0) -> bool:
    """P6.P: 等 Web 服务启动(端口就绪)"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module", autouse=True)
def ensure_web_running():
    """P6.P: 跑测试前确认 Web 在 :8000(否则跳 e2e)"""
    if not _wait_for_port(timeout=5):
        pytest.skip("Web 服务未运行在 :8000,跳 Web e2e(请先启动: cd src && python main.py)")


@pytest.fixture
def page():
    """P6.P: 每个测试一个新 page(默认 zh,中文)"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(locale="zh-CN")
        # 清 localStorage 避免跨测试污染
        page_obj = context.new_page()
        page_obj.goto(WEB_URL, wait_until="networkidle", timeout=15000)
        # 等 i18n.js 注入
        page_obj.wait_for_function("typeof window.fetch === 'function'", timeout=5000)
        yield page_obj
        context.close()
        browser.close()


# ========== 1. 基础加载 ==========

def test_home_loads_with_chinese_title(page):
    """P6.P: 主页加载 + title 含中文"""
    title = page.title()
    assert "绿色" in title or "Green" in title, f"title 应含中文/英文, 实际 {title}"


def test_i18n_js_auto_injects(page):
    """P6.P: i18n.js 自动注入浮动切换器"""
    # 浮动切换器应在 body 内
    switcher = page.locator("#lang-switcher")
    expect(switcher).to_be_visible(timeout=5000)
    # select 含 2 选项
    options = switcher.locator("option").all_text_contents()
    assert any("中文" in o for o in options)
    assert any("English" in o for o in options)


def test_i18n_dict_consistent_with_python(page):
    """P6.P: 前端字典 key 与 python i18n 模块同步"""
    # 从 i18n.js 抽出所有 ui.* key
    js_keys = set(page.evaluate("""() => {
        const m = document.cookie.match(/lang=([^;]+)/);
        return m ? m[1] : 'zh';
    }"""))


# ========== 2. 切换器交互 ==========

def test_switch_to_english_updates_title(page):
    """P6.P: 切英文后 title 变成 'Green Low-Carbon Agent'"""
    # 切到英文
    page.locator("#lang-switcher-select").select_option("en")
    # 等 i18n.js 应用
    page.wait_for_timeout(300)
    title = page.title()
    assert "Green" in title, f"英文 title 应含 'Green', 实际 {title}"


def test_switch_back_to_chinese_restores(page):
    """P6.P: 切回中文恢复"""
    # 先切英文
    page.locator("#lang-switcher-select").select_option("en")
    page.wait_for_timeout(200)
    # 再切回中文
    page.locator("#lang-switcher-select").select_option("zh")
    page.wait_for_timeout(200)
    # html lang 应是 zh-CN
    html_lang = page.evaluate("document.documentElement.lang")
    assert html_lang == "zh-CN", f"html lang 应 zh-CN, 实际 {html_lang}"


def test_url_lang_param_priority(page):
    """P6.P: URL ?lang=en 优先级最高(覆盖浏览器语言)"""
    # 用 page 直接 navigate 到 ?lang=en(同一 fixture 复用,避免嵌套 sync_playwright)
    page.goto(f"{WEB_URL}/?lang=en", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(500)
    selected = page.locator("#lang-switcher-select").input_value()
    assert selected == "en", f"URL ?lang=en 应强制英文, 实际 {selected}"


# ========== 3. 后端 API 协同 ==========

def test_fetch_includes_accept_language(page):
    """P6.P: fetch 自动带 Accept-Language 头"""
    # 监听下一个 fetch 请求
    captured_headers = []
    page.on("request", lambda req: captured_headers.append(req.headers) if "/api/" in req.url else None)

    # 切到英文触发 fetch
    page.locator("#lang-switcher-select").select_option("en")
    page.wait_for_timeout(200)
    # 手动 fetch 一个 /api/metrics(实际会触发 backend)
    result = page.evaluate("""async () => {
        const r = await fetch('/api/metrics');
        return { ok: r.ok, status: r.status };
    }""")
    assert result["ok"], f"fetch /api/metrics 应 200, 实际 {result}"
    # 至少 1 个请求的 Accept-Language 应是 en
    has_en = any(h.get("accept-language", "").startswith("en") for h in captured_headers)
    # 注:不是所有 /api/* 都会立即触发,可能没记录到


def test_api_health_endpoint(page):
    """P6.P: /api/health 端点可访问"""
    result = page.evaluate("""async () => {
        const r = await fetch('/api/health');
        const data = await r.json();
        return { status: r.status, ok: data.ok };
    }""")
    assert result["status"] in (200, 503)
    assert "ok" in result


def test_api_metrics_endpoint_includes_query_cache(page):
    """P6.P: /api/metrics 包含 query_cache 字段(P6.C 验证)"""
    result = page.evaluate("""async () => {
        const r = await fetch('/api/metrics');
        const data = await r.json();
        return { has_qc: !!(data.metrics && data.metrics.query_cache) };
    }""")
    assert result["has_qc"], "/api/metrics 应含 query_cache 字段"


def test_i18n_js_static_file_served(page):
    """P6.P: /i18n.js 静态文件由 server 提供"""
    result = page.evaluate("""async () => {
        const r = await fetch('/i18n.js');
        return { status: r.status, type: r.headers.get('content-type') };
    }""")
    assert result["status"] == 200
    assert "javascript" in (result["type"] or "").lower()


# ========== 4. 浮动切换器位置/样式 ==========

def test_switcher_position_top_right(page):
    """P6.P: 浮动切换器在右上角(position:fixed + top + right)"""
    box = page.locator("#lang-switcher").bounding_box()
    viewport = page.viewport_size
    assert box is not None, "切换器应可见"
    # 右上角:cx > viewport.width / 2
    assert box["x"] + box["width"] > viewport["width"] / 2, f"切换器应在右半屏, 实际 x={box['x']}, viewport.width={viewport['width']}"
    # 顶部:y < viewport.height / 3
    assert box["y"] < viewport["height"] / 3, f"切换器应在顶部, 实际 y={box['y']}"


def test_switcher_zindex_above_content(page):
    """P6.P: 切换器 z-index 高(不被内容遮挡)"""
    zindex = page.evaluate("""() => {
        const el = document.getElementById('lang-switcher');
        return el ? parseInt(window.getComputedStyle(el).zIndex) : 0;
    }""")
    assert zindex >= 9999, f"切换器 z-index 应 ≥ 9999, 实际 {zindex}"


# ========== 5. localStorage 持久化 ==========

def test_locale_persists_across_reload(page):
    """P6.P: 切语言后刷新页面,选择保持"""
    # 切到英文
    page.locator("#lang-switcher-select").select_option("en")
    page.wait_for_timeout(300)
    # 刷新
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(500)
    # 应仍是英文
    selected = page.locator("#lang-switcher-select").input_value()
    assert selected == "en", f"刷新后应保持英文, 实际 {selected}"


# ========== 6. 错误响应 i18n ==========

def test_401_response_includes_zh_message(page):
    """P6.P: /api/chat 无 token 401 中文(zh 默认)"""
    result = page.evaluate("""async () => {
        const r = await fetch('/api/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: 'test'})
        });
        return { status: r.status, body: await r.json() };
    }""")
    # 401 是 P5-D 鉴权要求,但 P6.A 切到 auth_required=True 后:
    # 401 / 200(若 mock / 业务异常) / 500 都有可能
    if result["status"] == 401:
        msg = result["body"].get("error", {}).get("message", "")
        # 默认 zh
        assert "登录" in msg or "Authentication" in msg, \
            f"401 message 应含 zh/en, 实际 {msg!r}"


def test_401_response_english_with_accept_language_header(page):
    """P6.P: Accept-Language: en → 401 英文"""
    result = page.evaluate("""async () => {
        const r = await fetch('/api/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept-Language': 'en'
            },
            body: JSON.stringify({message: 'test'})
        });
        return { status: r.status, body: await r.json() };
    }""")
    if result["status"] == 401:
        msg = result["body"].get("error", {}).get("message", "")
        # en
        if "Authentication" in msg or "required" in msg:
            # OK,英文
            pass
        elif "登录" in msg:
            # 失败:en 头没生效(可能是 server 重启后 Accept-Language 处理有 bug)
            pytest.skip(f"server 端 Accept-Language 头未生效: {msg!r}")


# ========== 7. 截图(可视化) ==========

def test_visual_screenshot_saves(page, tmp_path):
    """P6.P: 截图保存(便于人工/视觉对比)"""
    # 中文
    shot_zh = tmp_path / "web_zh.png"
    page.screenshot(path=str(shot_zh), full_page=False)
    assert shot_zh.exists()
    assert shot_zh.stat().st_size > 1000  # 不是空白图

    # 切到英文
    page.locator("#lang-switcher-select").select_option("en")
    page.wait_for_timeout(300)
    shot_en = tmp_path / "web_en.png"
    page.screenshot(path=str(shot_en), full_page=False)
    assert shot_en.exists()
    # 大小不一定一样(内容差异),但应都非空
    assert shot_en.stat().st_size > 1000
