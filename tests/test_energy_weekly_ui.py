"""Browser interaction against real energy handlers and isolated SQLite data.

Run explicitly on a machine with Playwright and Edge installed.
"""
import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in browser integration test")
def test_week_ui_roundtrip(tmp_path, monkeypatch):
    from playwright.sync_api import sync_playwright
    from server.routers.energy import register_energy_routes
    import agent.energy.household_store as hs
    import agent.energy.weekly as weekly
    import agent.energy.delegation as delegation
    db = tmp_path / "households.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE household_profiles(user_id TEXT PRIMARY KEY, profile_json TEXT, delegation_level INTEGER, updated_at TEXT);
        CREATE TABLE household_plans(plan_id TEXT PRIMARY KEY, user_id TEXT, variant_id TEXT, plan_json TEXT, status TEXT, created_at TEXT);
    """)
    conn.close()
    connections = []
    def connection():
        c = sqlite3.connect(db); c.row_factory = sqlite3.Row; connections.append(c); return c
    monkeypatch.setattr(hs, "_get_conn", connection)
    monkeypatch.setattr(weekly, "HOUSEHOLDS_DB", db)
    monkeypatch.setattr(delegation, "get_delegation_level", lambda uid: 1)
    monkeypatch.setattr("server.routers.energy._audit", lambda *a, **k: None)
    routes = {}
    register_energy_routes(SimpleNamespace(add_route=lambda method, path, fn, **kw: routes.update({(method, path): fn})))
    html = (Path(__file__).parents[1] / "web/energy.html").read_text(encoding="utf-8")
    errors = []
    def serve(route):
        req = route.request
        path = urlparse(req.url).path
        if path == "/energy.html":
            route.fulfill(content_type="text/html", body=html)
            return
        fn = routes.get((req.method, path))
        if fn is None:
            route.fulfill(status=404, content_type="application/json", body='{"message":"not found"}')
            return
        handler = SimpleNamespace(current_user={"user_id": "ui-alice"}, command=req.method, path=path)
        handler.send_json = lambda body: setattr(handler, "result", body)
        try:
            fn(handler, json.loads(req.post_data or "{}"))
            route.fulfill(content_type="application/json", body=json.dumps(handler.result))
        except Exception as exc:
            errors.append(repr(exc))
            route.fulfill(status=400, content_type="application/json", body=json.dumps({"message": str(exc)}))
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/*", serve)
            page.add_init_script("localStorage.setItem('green_energy_token','test'); localStorage.setItem('green_energy_user',JSON.stringify({userId:'ui-alice',username:'Test'}));")
            page.goto("http://energy.test/energy.html")
            assert page.locator("#f-familySize").input_value() == ""
            page.locator("#f-familySize").fill("3")
            page.locator("#f-usesGas").select_option("false")
            page.locator("#f-appliances .chip", has_text="冰箱").click()
            page.locator("#f-appliances .chip", has_text="洗衣机").click()
            page.locator("#saveProfileBtn").click()
            page.wait_for_function("document.getElementById('profileResult').textContent.includes('已保存')")
            page.locator('[data-tab="plan"]').click()
            page.locator("#startWeekBtn").wait_for()
            assert "每月" not in page.locator("#planResult").inner_text()
            page.locator("#startWeekBtn").click()
            page.locator('[data-tab="today"]').click()
            page.locator("#reloadWeekBtn").click()
            row = page.locator("#weekResult .action-item").first
            row.wait_for()
            row.locator('select[aria-label="完成情况"]').select_option("partial")
            row.locator('select[aria-label="困难原因"]').select_option("comfort")
            row.get_by_role("button", name="保存反馈").click()
            page.wait_for_function("document.getElementById('weekResult').textContent.includes('共1条记录')")
            page.reload()
            page.locator('[data-tab="today"]').click()
            page.wait_for_function("document.getElementById('weekResult').textContent.includes('共1条记录')")
            assert "缩小改变幅度" in page.locator("#weekResult").inner_text()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert not errors, errors
            browser.close()
    finally:
        for c in connections: c.close()
