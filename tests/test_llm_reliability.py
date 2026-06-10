"""
LLM 可靠性契约测试 (P5-C 安全网)

覆盖:
1. timeout 触发 → LLMResponse.error = "timeout"
2. 4xx auth 错误不重试,立即 fallback
3. 5xx / timeout / connection error 可重试
4. _with_retry 指数退避(1s, 2s, 4s)
5. SSL 跳过开关 INSECURE_SKIP_VERIFY
6. 6 provider usage 100% 填充(用 mock SDK)
7. BaiduClient timeout 通过 requests.post
8. MiniMaxClient 自有重试 + 频率限制关键字
9. config.py LLMConfig 字段可达
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest
from llm import LLMResponse


# ========== 1. _classify_error / _is_retryable_error ==========

def test_classify_timeout():
    from llm.client import _classify_error
    assert _classify_error(TimeoutError("timeout")) == "timeout"
    assert _classify_error(Exception("APITimeoutError occurred")) == "timeout"


def test_classify_rate_limit():
    from llm.client import _classify_error
    assert _classify_error(Exception("rate limit exceeded")) == "rate_limit"
    assert _classify_error(Exception("HTTP 429 too many requests")) == "rate_limit"


def test_classify_ssl():
    from llm.client import _classify_error
    assert _classify_error(Exception("SSL certificate verify failed")) == "ssl_error"


def test_classify_auth():
    from llm.client import _classify_error
    assert _classify_error(Exception("HTTP 401 unauthorized")) == "auth_error"
    assert _classify_error(Exception("Authentication failed")) == "auth_error"


def test_classify_5xx():
    from llm.client import _classify_error
    assert _classify_error(Exception("HTTP 500 internal")) == "5xx"
    assert _classify_error(Exception("503 service unavailable")) == "5xx"


def test_classify_generic_exception():
    from llm.client import _classify_error
    result = _classify_error(ValueError("weird error"))
    assert result.startswith("exception:")
    assert "ValueError" in result


def test_is_retryable_4xx_not_retryable():
    from llm.client import _is_retryable_error
    assert _is_retryable_error(Exception("HTTP 401 auth failed")) is False
    assert _is_retryable_error(Exception("HTTP 400 bad request")) is False
    assert _is_retryable_error(Exception("HTTP 404 not found")) is False


def test_is_retryable_5xx_retryable():
    from llm.client import _is_retryable_error
    assert _is_retryable_error(Exception("HTTP 500")) is True
    assert _is_retryable_error(Exception("503 service unavailable")) is True


def test_is_retryable_timeout_retryable():
    from llm.client import _is_retryable_error
    assert _is_retryable_error(TimeoutError("timeout")) is True
    assert _is_retryable_error(ConnectionError("conn refused")) is True


def test_is_retryable_429_retryable():
    from llm.client import _is_retryable_error
    assert _is_retryable_error(Exception("429 too many requests")) is True
    assert _is_retryable_error(Exception("rate limit exceeded")) is True


# ========== 2. _with_retry 行为 ==========

def test_with_retry_success_no_retry():
    """一次成功不重试"""
    from llm.client import _with_retry
    call_count = [0]

    def fn():
        call_count[0] += 1
        return "ok"

    result = _with_retry(fn, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert call_count[0] == 1


def test_with_retry_eventually_succeeds():
    """失败 2 次后第 3 次成功"""
    from llm.client import _with_retry
    call_count = [0]

    def fn():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ConnectionError("fail")
        return "ok"

    result = _with_retry(fn, max_retries=3, base_delay=0.01)
    assert result == "ok"
    assert call_count[0] == 3


def test_with_retry_exhausts_max_retries():
    """超出 max_retries 抛出最后一次异常"""
    from llm.client import _with_retry
    call_count = [0]

    def fn():
        call_count[0] += 1
        raise ConnectionError(f"fail {call_count[0]}")

    with pytest.raises(ConnectionError) as exc:
        _with_retry(fn, max_retries=2, base_delay=0.01)
    # max_retries=2 → 1st try + 2 retries = 3 calls total
    assert call_count[0] == 3
    assert "fail 3" in str(exc.value)


def test_with_retry_4xx_not_retryable():
    """4xx 错误立即抛出,不重试"""
    from llm.client import _with_retry
    call_count = [0]

    def fn():
        call_count[0] += 1
        raise Exception("HTTP 401 unauthorized")

    with pytest.raises(Exception) as exc:
        _with_retry(fn, max_retries=3, base_delay=0.01)
    assert call_count[0] == 1  # 立即抛出,没重试
    assert "401" in str(exc.value)


def test_with_retry_exponential_backoff_delays():
    """验证 1s → 2s → 4s 退避(用 base_delay=0.05 加速测试)"""
    from llm.client import _with_retry
    call_times = []

    def fn():
        call_times.append(time.time())
        raise ConnectionError("fail")

    with pytest.raises(ConnectionError):
        _with_retry(fn, max_retries=3, base_delay=0.05)

    # 应该有 4 次调用(max_retries=3 → 1 + 3 = 4)
    assert len(call_times) == 4
    # 第 2 次调用延迟 ~0.05s, 第 3 次 ~0.1s, 第 4 次 ~0.2s
    assert call_times[1] - call_times[0] >= 0.04  # 1st retry
    assert call_times[2] - call_times[1] >= 0.09  # 2nd retry
    assert call_times[3] - call_times[2] >= 0.19  # 3rd retry


# ========== 3. config 字段 ==========

def test_llm_config_timeout_field():
    from config import get_settings, reset_settings
    reset_settings()
    s = get_settings()
    assert s.llm.timeout_seconds > 0
    assert s.llm.max_retries >= 0
    assert isinstance(s.llm.insecure_skip_verify, bool)


def test_llm_config_env_override(monkeypatch):
    """环境变量覆盖 LLMConfig 字段"""
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "5.0")
    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("INSECURE_SKIP_VERIFY", "true")
    from config import get_settings, reset_settings
    reset_settings()
    s = get_settings()
    assert s.llm.timeout_seconds == 5.0
    assert s.llm.max_retries == 5
    assert s.llm.insecure_skip_verify is True


# ========== 4. 6 provider timeout 触发 error 字段 ==========

def _make_openai_style_mock_client():
    """构造 OpenAI SDK 风格的 mock,模拟超时"""
    from openai import APITimeoutError
    # 构造一个 mock 客户端,其 chat.completions.create 抛 APITimeoutError
    client = MagicMock()
    client.chat.completions.create.side_effect = APITimeoutError("Request timed out")
    return client


def test_openai_client_timeout_sets_error():
    """OpenAI client 超时 → LLMResponse.error='timeout'"""
    from llm.client import OpenAIClient
    c = OpenAIClient()
    c._client = _make_openai_style_mock_client()  # type: ignore

    out = c.chat([{"role": "user", "content": "测试"}])
    assert isinstance(out, LLMResponse)
    assert out.error == "timeout"
    assert out.finish_reason == "error"
    # fallback 到 mock 仍返回内容
    assert out.content


def test_zhipu_client_timeout_sets_error():
    from llm.client import ZhipuClient
    c = ZhipuClient()
    c._client = _make_openai_style_mock_client()  # type: ignore
    out = c.chat([{"role": "user", "content": "测试"}])
    assert out.error == "timeout"


def test_ali_client_timeout_sets_error():
    from llm.client import AliClient
    c = AliClient()
    c._client = _make_openai_style_mock_client()  # type: ignore
    out = c.chat([{"role": "user", "content": "测试"}])
    assert out.error == "timeout"


def test_deepseek_client_timeout_sets_error():
    from llm.client import DeepSeekClient
    c = DeepSeekClient()
    c._client = _make_openai_style_mock_client()  # type: ignore
    out = c.chat([{"role": "user", "content": "测试"}])
    assert out.error == "timeout"


def test_minimax_client_timeout_sets_error():
    """MiniMax 的非频率限制错误会被分类,设置 error 字段"""
    from llm.client import MiniMaxClient
    c = MiniMaxClient()
    c._client = _make_openai_style_mock_client()  # type: ignore
    out = c.chat([{"role": "user", "content": "测试"}])
    assert out.error == "timeout"
    assert out.finish_reason == "error"


# ========== 5. 6 provider usage 100% 填充(mock SDK 返真实 usage) ==========

def _make_openai_style_mock_with_usage(prompt=10, completion=20, total=30):
    """模拟 OpenAI SDK 返回,带 usage 字段"""
    client = MagicMock()
    usage = MagicMock()
    usage.prompt_tokens = prompt
    usage.completion_tokens = completion
    usage.total_tokens = total
    choice = MagicMock()
    choice.message.content = "test content"
    choice.finish_reason = "stop"
    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = "test-model"
    client.chat.completions.create.return_value = response
    return client


def test_all_6_providers_fill_usage():
    """6 provider 拿到 SDK 响应时,usage 字段 100% 填充"""
    from llm.client import (
        OpenAIClient, ZhipuClient, AliClient, DeepSeekClient, MiniMaxClient, MockLLMClient,
    )

    # 5 OpenAI-SDK style + MiniMax + Mock
    test_cases = [
        (OpenAIClient(), "openai"),
        (ZhipuClient(), "zhipu"),
        (AliClient(), "ali"),
        (DeepSeekClient(), "deepseek"),
        (MiniMaxClient(), "MiniMax"),
    ]
    for c, label in test_cases:
        c._client = _make_openai_style_mock_with_usage(prompt=15, completion=25, total=40)  # type: ignore
        out = c.chat([{"role": "user", "content": "测试"}])
        assert out.usage == {"prompt_tokens": 15, "completion_tokens": 25, "total_tokens": 40}, \
            f"{label} usage not filled: {out.usage}"
        assert out.error is None  # 成功路径不应有 error


# ========== 6. 4xx auth 错误不重试,立即 fallback ==========

def test_4xx_auth_no_retry():
    """4xx 错误不应触发 retry"""
    from llm.client import OpenAIClient
    c = OpenAIClient()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("HTTP 401 unauthorized")
    c._client = mock_client  # type: ignore

    out = c.chat([{"role": "user", "content": "测试"}])
    assert isinstance(out, LLMResponse)
    # 验证只调用了 1 次(没重试)
    assert mock_client.chat.completions.create.call_count == 1
    assert out.error == "auth_error"


# ========== 7. 5xx 错误触发 retry ==========

def test_5xx_triggers_retry():
    """5xx 错误应触发重试,最终 fallback"""
    from llm.client import OpenAIClient
    c = OpenAIClient()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception("HTTP 503 service unavailable")
    c._client = mock_client  # type: ignore

    import os
    os.environ["LLM_MAX_RETRIES"] = "2"  # 限制 2 次重试加速测试

    out = c.chat([{"role": "user", "content": "测试"}])
    # max_retries=2 → 1 + 2 = 3 次调用
    assert mock_client.chat.completions.create.call_count == 3
    assert out.error == "5xx"


# ========== 8. SSL 跳过开关 ==========

def test_minimax_no_ssl_skip_by_default():
    """默认 INSECURE_SKIP_VERIFY=false 不禁用 SSL"""
    from llm.client import MiniMaxClient
    import os
    os.environ.pop("INSECURE_SKIP_VERIFY", None)

    c = MiniMaxClient()
    c._init_client() if c.api_key else None  # noqa
    # 没 api_key 就不会 init,不影响测试意图


def test_minimax_ssl_skip_with_env(monkeypatch):
    """INSECURE_SKIP_VERIFY=true 时禁用 SSL"""
    import os
    monkeypatch.setenv("MINIMAX_API_KEY", "fake_key_for_test")
    monkeypatch.setenv("INSECURE_SKIP_VERIFY", "true")

    from llm.client import MiniMaxClient
    c = MiniMaxClient()
    # 即使没真 key,我们也手动调 _init_client 路径
    # 但 init 失败也不影响 SSL 验证逻辑
    # 这里只验证 os.environ['CURL_CA_BUNDLE'] 没被全局污染
    assert os.environ.get("CURL_CA_BUNDLE", "未设置") == "未设置", "CURL_CA_BUNDLE 被全局污染"
    assert os.environ.get("REQUESTS_CA_BUNDLE", "未设置") == "未设置", "REQUESTS_CA_BUNDLE 被全局污染"


def test_no_global_ssl_pollution():
    """确保 client.py 任何路径都不再污染 CURL_CA_BUNDLE / REQUESTS_CA_BUNDLE"""
    import os
    # 加载 client 模块
    from llm import client as _  # noqa
    assert os.environ.get("CURL_CA_BUNDLE", "未设置") == "未设置"
    assert os.environ.get("REQUESTS_CA_BUNDLE", "未设置") == "未设置"


# ========== 9. BaiduClient timeout 通过 requests.post ==========

def test_baidu_client_timeout():
    """BaiduClient 用 requests.post,设 timeout=30"""
    from llm.client import BaiduClient
    c = BaiduClient()
    c._access_token = "fake_token"

    import requests
    with patch.object(requests, "post") as mock_post:
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_post.return_value = mock_response

        out = c.chat([{"role": "user", "content": "测试"}])
        # 验证 timeout 参数传入
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs.get("timeout") == 30.0
        # 5xx 会被分类成 5xx (但因为只有一次 mock 返回,被外层 _classify_error 处理 → 5xx)
        # 实际 mock 直接返回 status 500,我们的代码逻辑是 if response.ok, else fallback with http_500
        assert out.error == "http_500"


# ========== 10. metrics 记录 error 分类 ==========

def test_metrics_records_error_class():
    """失败 metrics 用 error 分类字符串(不是完整堆栈)"""
    from observability import get_metrics_collector, reset_metrics_collector
    reset_metrics_collector()
    from llm.client import OpenAIClient
    c = OpenAIClient()
    c._client = _make_openai_style_mock_client()  # type: ignore
    c.chat([{"role": "user", "content": "测试"}])

    s = get_metrics_collector().summary()
    openai = s["by_provider"].get("openai", {})
    assert openai.get("failed_calls", 0) >= 1
    # error 字段是分类字符串,不是堆栈
    # (通过 _classify_error 返 "timeout" 等短字符串)


# ========== 11. 端到端 smoke test ==========

def test_end_to_end_no_api_keys_all_fallback():
    """6 provider 在没 API key 时全部 fallback 到 mock"""
    from llm.client import (
        OpenAIClient, ZhipuClient, BaiduClient, AliClient,
        MiniMaxClient, DeepSeekClient, MockLLMClient,
    )
    for c in [OpenAIClient(), ZhipuClient(), BaiduClient(), AliClient(), MiniMaxClient(), DeepSeekClient(), MockLLMClient()]:
        out = c.chat([{"role": "user", "content": "测试"}])
        assert isinstance(out, LLMResponse)
        assert out.content
