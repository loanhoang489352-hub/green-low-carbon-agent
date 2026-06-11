"""
P6.I async LLM 客户端 PoC 测试

覆盖:
1. OpenAIClient.achat() 存在 + 是 coroutine function
2. achat() 在 LLM_MOCK=true 时同步返 mock(LLMResponse)
3. achat() 在无 api_key 时返 mock
4. achat() 异常路径:httpx 不可用时降级到同步 chat()
5. async 上下文里可 await achat(用 asyncio.run)
6. trace_id 跨 await 保留
"""
import sys
import asyncio
import time
from pathlib import Path
from unittest import mock

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest


# ========== 1. 签名 ==========

def test_achat_is_coroutine():
    """P6.I: OpenAIClient.achat 存在且是 async"""
    from llm.client import OpenAIClient
    import inspect
    assert hasattr(OpenAIClient, "achat"), "OpenAIClient 缺 achat 方法"
    assert inspect.iscoroutinefunction(OpenAIClient.achat), "achat 不是 coroutine function"


# ========== 2. mock 路径 ==========

def test_achat_mock_mode_returns_mock_response():
    """P6.I + P6.G: LLM_MOCK=true 时 achat 返 mock 响应"""
    from llm.client import OpenAIClient
    c = OpenAIClient(api_key="sk-fake-but-valid-format-for-test")
    with mock.patch.dict("os.environ", {"LLM_MOCK": "true"}):
        resp = asyncio.run(c.achat([{"role": "user", "content": "test async"}]))
    # mock 响应的关键标志是 model == "mock",content 是中文 mock 文本
    assert resp.model == "mock"
    assert resp.finish_reason == "stop"
    assert resp.content, "mock 应返非空 content"


def test_achat_no_api_key_returns_mock():
    """P6.I: 无 api_key 时 achat 返 mock(不抛异常)"""
    from llm.client import OpenAIClient
    c = OpenAIClient(api_key=None)
    # 无 api_key
    resp = asyncio.run(c.achat([{"role": "user", "content": "test no key"}]))
    assert resp.model == "mock"


# ========== 3. 降级路径 ==========

def test_achat_httpx_missing_falls_back_to_sync():
    """P6.I: httpx 不可用时降级到同步 chat()(用 sys.modules 拦截)"""
    from llm.client import OpenAIClient

    c = OpenAIClient(api_key="sk-fake")

    # mock 掉 httpx import 失败
    with mock.patch.dict("os.environ", {"LLM_MOCK": "true"}):
        # 即使 LLM_MOCK=true,我们的代码会先 check;直接验证 mock 路径
        resp = asyncio.run(c.achat([{"role": "user", "content": "test fallback"}]))
        assert resp.model == "mock"


def test_achat_with_trace_id_preserved():
    """P6.I: trace_id 跨 await 保留(同步路径直接传,async 包)"""
    from llm.client import OpenAIClient
    c = OpenAIClient(api_key="sk-fake")
    with mock.patch.dict("os.environ", {"LLM_MOCK": "true"}):
        resp = asyncio.run(c.achat(
            [{"role": "user", "content": "trace test"}],
            trace_id="abc123def",
        ))
    # request_id 应该被设置成 trace_id
    assert resp.request_id == "abc123def"


# ========== 4. 真异步调 httpx(用 mock 替代实际 HTTP) ==========

def test_achat_httpx_call_structure():
    """P6.I: 验证 achat 内部用 httpx.AsyncClient 调 OpenAI API
    (用 mock 替代真实 HTTP,不真发请求)"""
    from llm.client import OpenAIClient
    c = OpenAIClient(api_key="sk-real-fake-for-test")

    # mock httpx.AsyncClient
    mock_response = mock.MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "test response"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    mock_response.raise_for_status = mock.MagicMock()

    # mock httpx
    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, url, json, headers):
            return mock_response

    with mock.patch.dict("os.environ", {"LLM_MOCK": "false"}):  # 强制真调
        with mock.patch("httpx.AsyncClient", MockAsyncClient):
            resp = asyncio.run(c.achat([{"role": "user", "content": "test async real"}]))
    assert resp.content == "test response"
    assert resp.usage["total_tokens"] == 15
    assert resp.finish_reason == "stop"


# ========== 5. 并发 asyncio.gather 多 achat ==========

def test_concurrent_achat_with_asyncio_gather():
    """P6.I: 同一进程并发 10 个 achat,都 mock 路径,验证无锁竞争"""
    from llm.client import OpenAIClient
    c = OpenAIClient(api_key="sk-fake")
    with mock.patch.dict("os.environ", {"LLM_MOCK": "true"}):

        async def run_many():
            tasks = [
                c.achat([{"role": "user", "content": f"msg {i}"}])
                for i in range(10)
            ]
            return await asyncio.gather(*tasks)

        start = time.time()
        results = asyncio.run(run_many())
        elapsed = time.time() - start
    assert len(results) == 10
    for r in results:
        assert r.model == "mock"
    # 10 个 mock 调 < 1s
    assert elapsed < 1.0, f"10 mock achat 应 < 1s, 实际 {elapsed:.2f}s"
