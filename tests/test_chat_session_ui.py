"""Isolated browser regression for session recovery and header layout."""
import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest


@pytest.mark.skipif(os.environ.get('RUN_BROWSER_TESTS') != '1', reason='Opt-in Edge test')
def test_chat_session_recovery():
    from playwright.sync_api import sync_playwright
    root = Path(__file__).parents[1] / 'web'
    calls = []
    def serve(route):
        path = urlparse(route.request.url).path
        if path.startswith('/api/'):
            if path == '/api/auth/check':
                data = {'valid': True, 'username': 'Test', 'user_id': 'profile-alice'}
            elif path.startswith('/api/chat'):
                calls.append((path, route.request.headers, route.request.post_data_json))
                if len(calls) == 1:
                    route.fulfill(status=401, content_type='application/json', body='{}')
                    return
                if path == '/api/chat':
                    route.fulfill(content_type='application/json', body=json.dumps({'message': 'Guest reply'}))
                    return
                route.fulfill(content_type='text/event-stream', body='event: done\ndata: '+json.dumps({'message': 'Plan ready'})+'\n\n')
                return
            else:
                data = {}
            route.fulfill(content_type='application/json', body=json.dumps(data))
            return
        file = root / (path.lstrip('/') or 'index.html')
        if file.is_file():
            route.fulfill(path=str(file))
        else:
            route.fulfill(status=404, body='')
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width': 1000, 'height': 900})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.route('**/*', serve)
        page.add_init_script("""
            localStorage.setItem('green_agent_session_id','old-token');
            localStorage.setItem('green_agent_account_id','account-alice');
            localStorage.setItem('green_agent_user_id','profile-alice');
        """)
        page.goto('http://green.test/')
        page.evaluate('async () => { await authReady; ensureBrowserLocation = async () => null; }')
        for width in (1000, 390):
            page.set_viewport_size({'width': width, 'height': 900})
            assert page.evaluate("getComputedStyle(document.querySelector('#connection-status')).position") == 'static'
            a = page.locator('#connection-status').bounding_box()
            b = page.locator('.header-icon').bounding_box()
            assert a['y'] >= b['y'] + b['height'] or a['x'] >= b['x'] + b['width']
        assert page.locator('a[href="/energy.html"]').count() == 0
        page.evaluate("document.getElementById('message-input').value='energy planning'; sendMessage()")
        page.wait_for_function("document.querySelector('.retry-btn') !== null")
        assert page.evaluate('sessionId') is None
        assert page.locator('.retry-btn').inner_text() == '登录后重试'
        assert page.locator('#chat-container .message.user').count() == 1
        # Simulate re-login, then retry the original failed message.
        page.evaluate("sessionId='fresh-token'; userId='profile-alice'")
        page.locator('.retry-btn').click(force=True)
        page.wait_for_function("document.querySelector('#chat-container').textContent.includes('Plan ready')")
        assert calls[1][1]['authorization'] == 'Bearer fresh-token'
        assert calls[1][2]['user_id'] == 'profile-alice'
        assert page.locator('#chat-container .message.user').count() == 1
        page.wait_for_function("!_isSending")
        page.evaluate("clearAuthSession(); isRegistered=true; document.getElementById('message-input').value='hello'; sendMessage()")
        page.wait_for_function("document.querySelector('#chat-container').textContent.includes('Guest reply')")
        assert calls[-1][0] == '/api/chat'
        assert 'authorization' not in calls[-1][1]
        assert calls[-1][2]['user_id'] == 'anonymous'
        assert not errors
        browser.close()
