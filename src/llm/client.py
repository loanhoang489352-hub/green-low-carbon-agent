"""
LLM客户端 - 统一管理大语言模型调用
支持 OpenAI API、本地模型、Mock模式
"""

import os
import sys

# P5-A.2: 统一 LLM 契约,client.py 也 import LLMResponse
from llm import LLMResponse

# P5-B: 可观测性 — trace_id + 结构化日志 + 指标
from observability import (
    new_trace_id,
    get_trace_id,
    get_logger,
    get_metrics_collector,
)

# Windows UTF-8 encoding setup - Only if not already wrapped (avoid duplicate wrapping)
if sys.platform == 'win32':
    import io
    if not isinstance(sys.stdout, io.TextIOWrapper) or sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import json
import time
import ssl
import random
import math
import ssl
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from typing import Optional, List, Dict, Any
from pathlib import Path
from collections import defaultdict
from datetime import datetime
import threading
import copy

# 项目路径
script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent


# P5-B: 模块级 logger (JSON formatter 自动注入 trace_id)
_logger = get_logger("llm.client")


def _provider_name(cls_name: str) -> str:
    """OpenAIClient -> openai, MockLLMClient -> mock"""
    return cls_name.replace("Client", "").lower()


# P5-C: 默认 LLM 调用超时/重试参数 (可被环境变量覆盖)
def _llm_timeout() -> float:
    return float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))


def _llm_max_retries() -> int:
    return int(os.environ.get("LLM_MAX_RETRIES", "2"))


def _is_retryable_error(exc: Exception) -> bool:
    """
    判断异常是否可重试 (P5-C)

    不可重试: 4xx 客户端错误 (auth, bad request, not found)
    可重试: timeout / connection / 5xx / 429
    """
    # timeout
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    # OpenAI SDK 异常层级
    exc_name = type(exc).__name__
    if exc_name in ("APITimeoutError", "APIConnectionError", "InternalServerError", "RateLimitError"):
        return True
    exc_str = str(exc).lower()
    # 5xx
    if any(code in exc_str for code in ["500", "502", "503", "504", "internal server error", "bad gateway", "service unavailable"]):
        return True
    # 429
    if "429" in exc_str or "rate limit" in exc_str or "too many requests" in exc_str:
        return True
    # SSL 网络问题
    if "ssl" in exc_str or "certificate" in exc_str:
        return True
    # 4xx 不重试
    if any(code in exc_str for code in ["401", "403", "404", "400"]):
        return False
    return True  # 默认重试


def _classify_error(exc: Exception) -> str:
    """
    把异常归类为短字符串,填入 LLMResponse.error

    返回: "timeout" / "rate_limit" / "ssl_error" / "auth_error" / "5xx" / "exception: <msg>"
    """
    exc_str = str(exc).lower()
    exc_name = type(exc).__name__
    if isinstance(exc, TimeoutError) or exc_name == "APITimeoutError" or "timeout" in exc_str:
        return "timeout"
    if exc_name == "RateLimitError" or "429" in exc_str or "rate limit" in exc_str:
        return "rate_limit"
    if "ssl" in exc_str or "certificate" in exc_str:
        return "ssl_error"
    if any(code in exc_str for code in ["401", "403", "authentication", "unauthorized"]):
        return "auth_error"
    if any(code in exc_str for code in ["500", "502", "503", "504"]):
        return "5xx"
    return f"exception: {type(exc).__name__}: {str(exc)[:100]}"


def _with_retry(fn, max_retries: int, base_delay: float = 1.0, label: str = "llm"):
    """
    指数退避重试包装 (P5-C)
    - 1st retry after 1s, 2nd after 2s, 3rd after 4s ...
    - 不可重试异常立即抛出
    - 超出 max_retries 抛出最后一次异常
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            retryable = _is_retryable_error(e)
            if not retryable or attempt >= max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            _logger.warning(
                "llm_retry",
                extra={
                    "event": "llm_retry", "label": label,
                    "attempt": attempt + 1, "max_retries": max_retries,
                    "delay_s": delay, "error": str(e)[:200],
                },
            )
            time.sleep(delay)
    raise last_exc  # pragma: no cover


class LLMClient:
    """LLM客户端基类"""
    
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.7, max_tokens: int = 2000):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """发送对话请求"""
        raise NotImplementedError

    def is_available(self) -> bool:
        """检查是否可用"""
        raise NotImplementedError

    def _call_openai_sdk(
        self,
        messages: List[Dict[str, str]],
        kwargs: Dict[str, Any],
        error_label: str,
        trace_id: str,
    ) -> LLMResponse:
        """
        OpenAI-SDK 兼容客户端的通用调用路径 (P5-B + P5-C)

        适用: OpenAI / Zhipu / Ali / DeepSeek (都用 openai SDK 风格)
        P5-C 加固:
        - timeout=LLM_TIMEOUT_SECONDS (默认 30s)
        - max_retries=0 (禁用 SDK 内置重试,由外层 _with_retry 统一管)
        - 3 次重试 + 1s→2s→4s 指数退避
        - LLMResponse.error 字段填充 error 分类
        """
        provider = _provider_name(type(self).__name__)
        start = time.time()
        timeout_s = _llm_timeout()
        max_retries = _llm_max_retries()

        def _do_call():
            return self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=kwargs.get("temperature", self.temperature),
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                timeout=timeout_s,
                # 禁用 SDK 内置重试,由 _with_retry 统一管
                max_retries=0,
            )

        try:
            response = _with_retry(_do_call, max_retries=max_retries, base_delay=1.0, label=error_label)
            latency_ms = round((time.time() - start) * 1000, 2)
            usage_dict = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            }
            _logger.info(
                "llm_call",
                extra={
                    "event": "llm_call", "trace_id": trace_id, "provider": provider,
                    "model": response.model, "latency_ms": latency_ms,
                    "prompt_tokens": usage_dict["prompt_tokens"],
                    "completion_tokens": usage_dict["completion_tokens"],
                    "total_tokens": usage_dict["total_tokens"],
                    "finish_reason": response.choices[0].finish_reason or "stop",
                    "success": True,
                },
            )
            get_metrics_collector().record(
                provider=provider, model=response.model, latency_ms=latency_ms, success=True,
                prompt_tokens=usage_dict["prompt_tokens"],
                completion_tokens=usage_dict["completion_tokens"],
                total_tokens=usage_dict["total_tokens"],
            )
            return LLMResponse(
                content=response.choices[0].message.content,
                model=response.model,
                usage=usage_dict,
                finish_reason=response.choices[0].finish_reason or "stop",
                latency_ms=latency_ms,
                request_id=trace_id,
            )
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 2)
            error_class = _classify_error(e)
            _logger.warning(
                "llm_call_failed",
                extra={
                    "event": "llm_call_failed", "trace_id": trace_id, "provider": provider,
                    "model": self.model, "latency_ms": latency_ms,
                    "error": str(e), "error_class": error_class, "success": False,
                },
            )
            get_metrics_collector().record(
                provider=provider, model=self.model,
                latency_ms=latency_ms, success=False, error=error_class,
            )
            print(f"[WARN]  {error_label} API调用失败 [{error_class}]: {e}")
            # P5-C: 即使 fallback 到 mock,LLMResponse.error 也填 error_class
            mock_resp = self._mock_response(messages, trace_id=trace_id)
            mock_resp.error = error_class
            mock_resp.finish_reason = "error"
            return mock_resp


class OpenAIClient(LLMClient):
    """OpenAI API 客户端"""
    
    def __init__(self, api_key: str = None, model: str = "gpt-4o-mini", 
                 temperature: float = 0.7, max_tokens: int = 2000):
        super().__init__(model, temperature, max_tokens)
        
        # 优先从环境变量获取
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._client = None
        
        if self.api_key and self.api_key != "sk-your-api-key-here":
            self._init_client()
    
    def _init_client(self):
        """初始化OpenAI客户端"""
        try:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
            print(f"[OK] OpenAI客户端初始化成功 (模型: {self.model})")
        except ImportError:
            print("[WARN]  openai包未安装，请运行: pip install openai")
            self._client = None
        except Exception as e:
            print(f"[WARN]  OpenAI客户端初始化失败: {e}")
            self._client = None
    
    def is_available(self) -> bool:
        """检查API是否可用"""
        return self._client is not None
    
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """发送对话请求 (P5-A.2: 返回 LLMResponse, P5-B: 注入 trace_id + 记录 metrics)"""
        trace_id = kwargs.pop("trace_id", None) or new_trace_id()
        if not self._client:
            return self._mock_response(messages, trace_id=trace_id)
        return self._call_openai_sdk(messages, kwargs, error_label="OpenAI", trace_id=trace_id)

    def _mock_response(self, messages: List[Dict[str, str]], trace_id: Optional[str] = None) -> LLMResponse:
        """Mock响应 (P5-A.2: 返回 LLMResponse, P5-B: 携带 trace_id + latency + 记录 metrics)"""
        start = time.time()
        provider = _provider_name(type(self).__name__)
        last_message = messages[-1]["content"] if messages else ""

        if "碳中和" in last_message:
            content = "碳中和是指通过节能减排、植树造林等方式，抵消自身产生的二氧化碳排放量，实现二氧化碳净零排放。中国承诺在2030年前碳达峰，2060年前实现碳中和。"
        elif "低碳" in last_message or "减排" in last_message:
            content = "低碳生活可以从身边小事做起：1) 尽量步行或骑行出行；2) 选择公共交通；3) 减少一次性用品使用；4) 节约用电用水。"
        elif "建议" in last_message or "推荐" in last_message:
            content = "我建议你从减少一次性塑料使用开始，比如自带购物袋和水杯。这不仅环保还能省钱！"
        else:
            content = "作为绿色低碳助手，我很乐意帮助你了解更多环保知识。请问你有什么具体想了解的吗？"

        latency_ms = round((time.time() - start) * 1000, 2)
        # P5-B: mock fallback 也要记 metrics
        _logger.info(
            "llm_call_mock_fallback",
            extra={
                "event": "llm_call_mock_fallback", "trace_id": trace_id,
                "provider": provider, "model": "mock", "latency_ms": latency_ms,
                "success": True, "reason": "no_api_key_or_unavailable",
            },
        )
        get_metrics_collector().record(
            provider=provider, model="mock", latency_ms=latency_ms, success=True,
        )
        return LLMResponse(
            content=content,
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop",
            request_id=trace_id,
            latency_ms=latency_ms,
        )


class ZhipuClient(LLMClient):
    """智谱 AI (GLM) 客户端"""

    def __init__(self, api_key: str = None, model: str = "glm-4-flash",
                 temperature: float = 0.7, max_tokens: int = 2000):
        super().__init__(model, temperature, max_tokens)
        self.api_key = api_key or os.environ.get("ZHIPU_API_KEY")
        self._client = None
        if self.api_key:
            self._init_client()

    def _init_client(self):
        try:
            import zhipuai
            self._client = zhipuai.ZhipuAI(api_key=self.api_key)
            print(f"[OK] 智谱AI客户端初始化成功 (模型: {self.model})")
        except ImportError:
            print("[WARN]  zhipuai包未安装，请运行: pip install zhipuai")
            self._client = None
        except Exception as e:
            print(f"[WARN]  智谱AI客户端初始化失败: {e}")
            self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """发送对话请求 (P5-A.2: 返回 LLMResponse, P5-B: 注入 trace_id + 记录 metrics)"""
        trace_id = kwargs.pop("trace_id", None) or new_trace_id()
        if not self._client:
            return self._mock_response(messages, trace_id=trace_id)
        return self._call_openai_sdk(messages, kwargs, error_label="智谱AI", trace_id=trace_id)

    def _mock_response(self, messages, trace_id: Optional[str] = None) -> LLMResponse:
        return MockLLMClient().chat(messages, trace_id=trace_id)


class BaiduClient(LLMClient):
    """百度文心一言客户端"""

    def __init__(self, api_key: str = None, model: str = "ernie-4.0-8k",
                 temperature: float = 0.7, max_tokens: int = 2000):
        super().__init__(model, temperature, max_tokens)
        self.api_key = api_key or os.environ.get("BAIDU_API_KEY")
        self.secret_key = os.environ.get("BAIDU_SECRET_KEY")
        self._access_token = None
        self._client = None
        if self.api_key and self.secret_key:
            self._init_client()

    def _init_client(self):
        try:
            import requests
            auth_url = (f"https://aip.baidubce.com/oauth/2.0/token"
                       f"?grant_type=client_credentials"
                       f"&client_id={self.api_key}"
                       f"&client_secret={self.secret_key}")
            response = requests.get(auth_url)
            if response.ok:
                self._access_token = response.json().get("access_token")
                print(f"[OK] 百度文心一言客户端初始化成功 (模型: {self.model})")
        except Exception as e:
            print(f"[WARN]  百度文心一言客户端初始化失败: {e}")

    def is_available(self) -> bool:
        return self._access_token is not None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """发送对话请求 (P5-A.2: 返回 LLMResponse, P5-B: 注入 trace_id + 记录 metrics, P5-C: timeout + retry)"""
        trace_id = kwargs.pop("trace_id", None) or new_trace_id()
        provider = _provider_name(type(self).__name__)
        start = time.time()
        timeout_s = _llm_timeout()
        max_retries = _llm_max_retries()

        if not self._access_token:
            return self._mock_response(messages, trace_id=trace_id)

        def _do_request():
            import requests
            url = (f"https://aip.baidubce.com/rpc/2.0/ai_custom/v1/"
                   f"wenxinworkshop/chat/completions?access_token={self._access_token}")
            payload = {
                "messages": messages,
                "temperature": kwargs.get("temperature", self.temperature),
                "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            }
            return requests.post(url, json=payload, timeout=timeout_s)

        try:
            response = _with_retry(_do_request, max_retries=max_retries, base_delay=1.0, label="百度文心一言")
            latency_ms = round((time.time() - start) * 1000, 2)
            if response.ok:
                result = response.json()
                content = result.get("result", "")
                usage = result.get("usage", {}) or {}
                usage_dict = {
                    "prompt_tokens": usage.get("prompt_tokens", 0) or 0,
                    "completion_tokens": usage.get("completion_tokens", 0) or 0,
                    "total_tokens": usage.get("total_tokens", 0) or 0,
                }
                finish_reason = result.get("finish_reason", "stop") or "stop"
                _logger.info(
                    "llm_call",
                    extra={
                        "event": "llm_call", "trace_id": trace_id, "provider": provider,
                        "model": self.model, "latency_ms": latency_ms,
                        "prompt_tokens": usage_dict["prompt_tokens"],
                        "completion_tokens": usage_dict["completion_tokens"],
                        "total_tokens": usage_dict["total_tokens"],
                        "finish_reason": finish_reason, "success": True,
                    },
                )
                get_metrics_collector().record(
                    provider=provider, model=self.model, latency_ms=latency_ms, success=True,
                    prompt_tokens=usage_dict["prompt_tokens"],
                    completion_tokens=usage_dict["completion_tokens"],
                    total_tokens=usage_dict["total_tokens"],
                )
                return LLMResponse(
                    content=content,
                    model=self.model,
                    usage=usage_dict,
                    finish_reason=finish_reason,
                    latency_ms=latency_ms,
                    request_id=trace_id,
                )
            # 4xx/5xx
            error_class = f"http_{response.status_code}"
            _logger.warning(
                "llm_call_failed",
                extra={
                    "event": "llm_call_failed", "trace_id": trace_id, "provider": provider,
                    "model": self.model, "latency_ms": latency_ms,
                    "error": error_class, "success": False,
                },
            )
            get_metrics_collector().record(
                provider=provider, model=self.model, latency_ms=latency_ms,
                success=False, error=error_class,
            )
            mock_resp = self._mock_response(messages, trace_id=trace_id)
            mock_resp.error = error_class
            mock_resp.finish_reason = "error"
            return mock_resp
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 2)
            error_class = _classify_error(e)
            _logger.warning(
                "llm_call_failed",
                extra={
                    "event": "llm_call_failed", "trace_id": trace_id, "provider": provider,
                    "model": self.model, "latency_ms": latency_ms,
                    "error": str(e), "error_class": error_class, "success": False,
                },
            )
            get_metrics_collector().record(
                provider=provider, model=self.model, latency_ms=latency_ms,
                success=False, error=error_class,
            )
            print(f"[WARN]  百度文心一言 API调用失败 [{error_class}]: {e}")
            mock_resp = self._mock_response(messages, trace_id=trace_id)
            mock_resp.error = error_class
            mock_resp.finish_reason = "error"
            return mock_resp

    def _mock_response(self, messages, trace_id: Optional[str] = None) -> LLMResponse:
        return MockLLMClient().chat(messages, trace_id=trace_id)


class AliClient(LLMClient):
    """阿里通义千问客户端"""

    def __init__(self, api_key: str = None, model: str = "qwen-plus",
                 temperature: float = 0.7, max_tokens: int = 2000):
        super().__init__(model, temperature, max_tokens)
        self.api_key = api_key or os.environ.get("ALI_API_KEY")
        self._client = None
        if self.api_key:
            self._init_client()

    def _init_client(self):
        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            print(f"[OK] 阿里通义千问客户端初始化成功 (模型: {self.model})")
        except ImportError:
            print("[WARN]  openai包未安装，请运行: pip install openai")
            self._client = None
        except Exception as e:
            print(f"[WARN]  阿里通义千问客户端初始化失败: {e}")
            self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """发送对话请求 (P5-A.2: 返回 LLMResponse, P5-B: 注入 trace_id + 记录 metrics)"""
        trace_id = kwargs.pop("trace_id", None) or new_trace_id()
        if not self._client:
            return self._mock_response(messages, trace_id=trace_id)
        return self._call_openai_sdk(messages, kwargs, error_label="阿里通义千问", trace_id=trace_id)

    def _mock_response(self, messages, trace_id: Optional[str] = None) -> LLMResponse:
        return MockLLMClient().chat(messages, trace_id=trace_id)


class MiniMaxClient(LLMClient):
    """MiniMax 海螺AI客户端"""

    def __init__(self, api_key: str = None, model: str = "abab6.5s",
                 temperature: float = 0.7, max_tokens: int = 2000):
        super().__init__(model, temperature, max_tokens)
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY")
        self.group_id = os.environ.get("MINIMAX_GROUP_ID")
        self._client = None
        self._rate_limit_delay = 1.0  # 频率限制后的等待时间（秒）
        self._max_retries = 3  # 最大重试次数
        if self.api_key:
            self._init_client()

    def _init_client(self):
        try:
            from openai import OpenAI

            # P5-C: SSL 跳过由 INSECURE_SKIP_VERIFY 控制(默认 False)
            # 通过 http_client=httpx.Client(verify=False) 局部生效,不再污染全局环境变量
            import os
            insecure = os.environ.get("INSECURE_SKIP_VERIFY", "").lower() in ("1", "true", "yes", "on")
            kwargs = {"api_key": self.api_key, "base_url": "https://api.minimax.chat/v1"}
            if insecure:
                import httpx
                kwargs["http_client"] = httpx.Client(verify=False)
                print("[WARN]  MiniMax 客户端 SSL 验证已禁用 (INSECURE_SKIP_VERIFY=true)")

            self._client = OpenAI(**kwargs)
            print(f"[OK] MiniMax客户端初始化成功 (模型: {self.model})")
        except ImportError:
            print("[WARN]  openai包未安装，请运行: pip install openai")
            self._client = None
        except Exception as e:
            print(f"[WARN]  MiniMax客户端初始化失败: {e}")
            self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """发送对话请求 (P5-A.2: 返回 LLMResponse,带指数退避重试; P5-B: 注入 trace_id + metrics; P5-C: timeout)"""
        trace_id = kwargs.pop("trace_id", None) or new_trace_id()
        provider = _provider_name(type(self).__name__)
        start = time.time()
        timeout_s = _llm_timeout()

        if not self._client:
            return self._mock_response(messages, trace_id=trace_id)

        last_error = None

        for attempt in range(self._max_retries):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=kwargs.get("temperature", self.temperature),
                    max_tokens=kwargs.get("max_tokens", self.max_tokens),
                    timeout=timeout_s,
                    max_retries=0,  # 禁用 SDK 内置重试
                )
                latency_ms = round((time.time() - start) * 1000, 2)
                usage_dict = {
                    "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                    "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                    "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
                }
                _logger.info(
                    "llm_call",
                    extra={
                        "event": "llm_call", "trace_id": trace_id, "provider": provider,
                        "model": response.model, "latency_ms": latency_ms,
                        "prompt_tokens": usage_dict["prompt_tokens"],
                        "completion_tokens": usage_dict["completion_tokens"],
                        "total_tokens": usage_dict["total_tokens"],
                        "finish_reason": response.choices[0].finish_reason or "stop",
                        "success": True, "attempts": attempt + 1,
                    },
                )
                get_metrics_collector().record(
                    provider=provider, model=response.model, latency_ms=latency_ms, success=True,
                    prompt_tokens=usage_dict["prompt_tokens"],
                    completion_tokens=usage_dict["completion_tokens"],
                    total_tokens=usage_dict["total_tokens"],
                )
                return LLMResponse(
                    content=response.choices[0].message.content,
                    model=response.model,
                    usage=usage_dict,
                    finish_reason=response.choices[0].finish_reason or "stop",
                    latency_ms=latency_ms,
                    request_id=trace_id,
                )

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # 检查是否是频率限制错误
                if any(keyword in error_str for keyword in ["rate limit", "429", "too many", "throttle", "请求过于频繁", "频率"]):
                    wait_time = self._rate_limit_delay * (2 ** attempt)  # 指数退避
                    print(f"MiniMax API 频率限制，等待 {wait_time:.1f} 秒后重试 (尝试 {attempt + 1}/{self._max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    # 其他错误，直接返回 mock
                    latency_ms = round((time.time() - start) * 1000, 2)
                    error_class = _classify_error(e)
                    _logger.warning(
                        "llm_call_failed",
                        extra={
                            "event": "llm_call_failed", "trace_id": trace_id, "provider": provider,
                            "model": self.model, "latency_ms": latency_ms,
                            "error": str(e), "error_class": error_class, "success": False, "attempts": attempt + 1,
                        },
                    )
                    get_metrics_collector().record(
                        provider=provider, model=self.model, latency_ms=latency_ms,
                        success=False, error=error_class,
                    )
                    print(f"MiniMax API 调用失败 [{error_class}]: {e}")
                    mock_resp = self._mock_response(messages, trace_id=trace_id)
                    mock_resp.error = error_class
                    mock_resp.finish_reason = "error"
                    return mock_resp

        # 所有重试都失败
        latency_ms = round((time.time() - start) * 1000, 2)
        error_class = _classify_error(last_error) if last_error else "max_retries_exceeded"
        _logger.warning(
            "llm_call_failed",
            extra={
                "event": "llm_call_failed", "trace_id": trace_id, "provider": provider,
                "model": self.model, "latency_ms": latency_ms,
                "error": f"max retries {self._max_retries} exhausted: {last_error}",
                "error_class": error_class, "success": False, "attempts": self._max_retries,
            },
        )
        get_metrics_collector().record(
            provider=provider, model=self.model, latency_ms=latency_ms,
            success=False, error=error_class,
        )
        print(f"MiniMax API 重试 {self._max_retries} 次后仍失败 [{error_class}]: {last_error}")
        mock_resp = self._mock_response(messages, trace_id=trace_id)
        mock_resp.error = error_class
        mock_resp.finish_reason = "error"
        return mock_resp

    def _mock_response(self, messages, trace_id: Optional[str] = None) -> LLMResponse:
        return MockLLMClient().chat(messages, trace_id=trace_id)


class DeepSeekClient(LLMClient):
    """DeepSeek 客户端"""

    def __init__(self, api_key: str = None, model: str = "deepseek-chat",
                 temperature: float = 0.7, max_tokens: int = 2000):
        super().__init__(model, temperature, max_tokens)
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self._client = None
        if self.api_key:
            self._init_client()

    def _init_client(self):
        try:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepseek.com"
            )
            print(f"[OK] DeepSeek客户端初始化成功 (模型: {self.model})")
        except ImportError:
            print("[WARN]  openai包未安装，请运行: pip install openai")
            self._client = None
        except Exception as e:
            print(f"[WARN]  DeepSeek客户端初始化失败: {e}")
            self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """发送对话请求 (P5-A.2: 返回 LLMResponse, P5-B: 注入 trace_id + 记录 metrics)"""
        trace_id = kwargs.pop("trace_id", None) or new_trace_id()
        if not self._client:
            return self._mock_response(messages, trace_id=trace_id)
        return self._call_openai_sdk(messages, kwargs, error_label="DeepSeek", trace_id=trace_id)

    def _mock_response(self, messages, trace_id: Optional[str] = None) -> LLMResponse:
        return MockLLMClient().chat(messages, trace_id=trace_id)


class MockLLMClient(LLMClient):
    """Mock LLM客户端（用于测试）"""

    def is_available(self) -> bool:
        return True

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """返回Mock响应 (P5-A.2: 统一返回 LLMResponse, P5-B: 注入 trace_id + 记录 metrics)"""
        trace_id = kwargs.get("trace_id") or new_trace_id()
        provider = _provider_name(type(self).__name__)
        start = time.time()
        last_message = messages[-1]["content"] if messages else ""

        if "碳" in last_message:
            content = "碳中和是指通过植树造林、节能减排等方式，抵消自身产生的二氧化碳排放，实现二氧化碳'净零排放'。"
        elif "建议" in last_message or "推荐" in last_message:
            content = "推荐你尝试以下低碳行动：1) 短距离出行选择步行或骑行；2) 购物时自带环保袋；3) 减少食物浪费。"
        else:
            content = "好的，让我来回答你的问题..."

        latency_ms = round((time.time() - start) * 1000, 2)
        _logger.info(
            "llm_call",
            extra={
                "event": "llm_call", "trace_id": trace_id, "provider": provider,
                "model": "mock", "latency_ms": latency_ms,
                "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                "finish_reason": "stop", "success": True,
            },
        )
        get_metrics_collector().record(
            provider=provider, model="mock", latency_ms=latency_ms, success=True,
        )
        return LLMResponse(
            content=content,
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop",
            latency_ms=latency_ms,
            request_id=trace_id,
        )


# ========== 贝叶斯模型路由器 ==========

class BetaDistribution:
    """Beta分布实现，用于贝叶斯推断的成功率建模"""

    def __init__(self, alpha: float = 1.0, beta: float = 1.0):
        self.alpha = alpha  # 成功次数 + 1（Beta(1,1) 为均匀先验）
        self.beta = beta    # 失败次数 + 1

    def sample(self) -> float:
        """从Beta分布中采样（使用Gamma函数近似）"""
        if self.alpha < 1:
            self.alpha = 1.0
        if self.beta < 1:
            self.beta = 1.0
        try:
            import numpy as np
            return float(np.random.beta(self.alpha, self.beta))
        except ImportError:
            return self._approx_sample()

    def _approx_sample(self) -> float:
        """无NumPy时的近似采样（使用均值-方差高斯混合 + 边界裁剪）"""
        mean = self.alpha / (self.alpha + self.beta)
        std = math.sqrt((self.alpha * self.beta) /
                        ((self.alpha + self.beta) ** 2 * (self.alpha + self.beta + 1)))
        # 加入足够的随机性（标准差至少0.15，确保有探索），再用均匀噪声增强
        sample_val = mean + random.gauss(0, max(std, 0.15)) + random.uniform(-0.1, 0.1)
        return max(0.005, min(0.995, sample_val))

    def mean(self) -> float:
        """Beta分布的均值"""
        return self.alpha / (self.alpha + self.beta)

    def variance(self) -> float:
        """Beta分布的方差"""
        denom = (self.alpha + self.beta) ** 2 * (self.alpha + self.beta + 1)
        return (self.alpha * self.beta) / denom if denom > 0 else 0.0

    def update(self, success: bool, cost_ms: float = None, confidence: float = 1.0):
        """
        根据观测结果更新Beta分布参数

        Args:
            success: 请求是否成功
            cost_ms: 响应耗时（毫秒），用于成本感知
            confidence: 响应置信度（0-1），由LLM输出质量评估
        """
        if success:
            self.alpha += confidence
        else:
            self.beta += 1.0

    def probability_of_beating(self, other: "BetaDistribution") -> float:
        """
        计算本分布均值优于另一个分布的概率
        使用蒙特卡洛采样估算 P(theta_a > theta_b)
        """
        count = 0
        trials = 1000
        for _ in range(trials):
            if self.sample() > other.sample():
                count += 1
        return count / trials

    def to_dict(self) -> Dict:
        return {"alpha": self.alpha, "beta": self.beta, "mean": round(self.mean(), 4)}


class ModelStats:
    """单个模型的统计信息"""

    def __init__(self, model_name: str, provider: str):
        self.model_name = model_name
        self.provider = provider
        self.success_dist = BetaDistribution(1.0, 1.0)
        self.cost_dist = BetaDistribution(1.0, 100.0)  # 成本分布，高beta=低cost偏好
        self.total_calls = 0
        self.success_calls = 0
        self.failed_calls = 0
        self.total_cost_ms = 0.0
        self.avg_latency_ms = 0.0
        self.history: List[Dict] = []
        self._lock = threading.Lock()

    def record_call(self, success: bool, latency_ms: float, response: str = ""):
        """记录一次调用"""
        with self._lock:
            self.total_calls += 1
            self.total_cost_ms += latency_ms
            self.avg_latency_ms = self.total_cost_ms / self.total_calls

            # 评估响应质量（简单启发式）
            quality = self._assess_quality(response, success)
            self.success_dist.update(success, latency_ms, quality)

            if success:
                self.success_calls += 1
            else:
                self.failed_calls += 1

            self.history.append({
                "timestamp": datetime.now().isoformat(),
                "success": success,
                "latency_ms": round(latency_ms, 1),
                "quality": quality
            })
            # 保留最近100条历史
            if len(self.history) > 100:
                self.history = self.history[-100:]

    def _assess_quality(self, response: str, success: bool) -> float:
        """评估响应质量（0-1）"""
        if not success:
            return 0.1
        if not response:
            return 0.3

        quality = 0.6  # 基础分（提高默认分，减少对探索的干扰）

        # 有实质内容加分
        if len(response) > 50:
            quality += 0.1
        if len(response) > 200:
            quality += 0.1

        # 检查是否Mock响应（轻微降权，不完全排除）
        mock_indicators = ["好的，让我来回答", "[模拟]", "[Mock]", "mock response"]
        mock_count = sum(1 for ind in mock_indicators if ind in response)
        quality -= mock_count * 0.05  # 每个指标只扣0.05

        # 是否有中文（加分，因为项目面向中文用户）
        has_chinese = any('\u4e00' <= c <= '\u9fff' for c in response)
        if has_chinese:
            quality += 0.1

        return max(0.1, min(1.0, quality))

    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.success_calls / self.total_calls

    def to_dict(self) -> Dict:
        return {
            "model": self.model_name,
            "provider": self.provider,
            "total_calls": self.total_calls,
            "success_calls": self.success_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(self.success_rate(), 4),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "success_dist": self.success_dist.to_dict(),
            "last_call": self.history[-1] if self.history else None
        }


class BayesianModelRouter:
    """
    贝叶斯模型路由器

    使用Beta-Bernoulli多臂老虎机框架对多个LLM模型进行概率建模，
    支持Thompson Sampling和UCB两种选择策略，自动学习最优模型。

    核心思想：
    - 每个模型的成功率建模为Beta分布
    - 每次调用后根据结果更新后验分布
    - 选择时从各模型的后验分布中采样，选择采样值最高的模型
    """

    STRATEGY_THOMPSON = "thompson"    # Thompson Sampling - 探索/利用平衡
    STRATEGY_UCB = "ucb"             # Upper Confidence Bound - 乐观估计
    STRATEGY_GREEDY = "greedy"       # 简单贪心 - 始终选最高均值
    STRATEGY_RANDOM = "random"       # 随机探索

    def __init__(
        self,
        strategy: str = STRATEGY_THOMPSON,
        exploration_weight: float = 2.0,
        min_samples: int = 3,
        auto_add_clients: bool = True
    ):
        self.strategy = strategy
        self.exploration_weight = exploration_weight  # UCB的探索系数
        self.min_samples = min_samples  # 最少采样次数后才考虑选择
        self.auto_add = auto_add_clients

        self._models: Dict[str, ModelStats] = {}
        self._clients: Dict[str, LLMClient] = {}
        # RLock: get_recommendation() 嵌套调用 get_best_model(),普通 Lock 会同线程死锁
        self._lock = threading.RLock()
        self._total_decisions = 0

        if auto_add_clients:
            self._register_default_clients()

    def _register_default_clients(self):
        """注册默认的LLM客户端"""
        default_providers = {
            "openai": ("gpt-4o-mini", OpenAIClient),
            "deepseek": ("deepseek-chat", DeepSeekClient),
            "zhipu": ("glm-4-flash", ZhipuClient),
            "minimax": ("MiniMax-Text-01", MiniMaxClient),
            "ali": ("qwen-plus", AliClient),
        }

        for name, (model, client_cls) in default_providers.items():
            try:
                client = client_cls()
                self.register_model(name, client, model)
            except Exception as e:
                print(f"[BayesianRouter] 注册 {name} 失败: {e}")

    def register_model(self, model_id: str, client: LLMClient, model_name: str = None):
        """注册一个模型到路由器"""
        with self._lock:
            if model_id not in self._models:
                self._models[model_id] = ModelStats(model_name or model_id, model_id)
            self._clients[model_id] = client

    def unregister_model(self, model_id: str):
        """从路由器移除一个模型"""
        with self._lock:
            self._models.pop(model_id, None)
            self._clients.pop(model_id, None)

    def select_model(self) -> str:
        """
        根据当前策略选择最优模型

        Returns:
            被选中的模型ID
        """
        with self._lock:
            available = [mid for mid in self._models if self._models[mid].total_calls > 0]
            if not available:
                return list(self._models.keys())[0] if self._models else "openai"

            if self.strategy == self.STRATEGY_THOMPSON:
                return self._select_thompson(available)
            elif self.strategy == self.STRATEGY_UCB:
                return self._select_ucb(available)
            elif self.strategy == self.STRATEGY_GREEDY:
                return self._select_greedy(available)
            else:
                return self._select_random(available)

    def _select_thompson(self, available: List[str]) -> str:
        """Thompson Sampling: 从每个模型的Beta分布中采样，选择最高的"""
        scores = {}
        for mid in available:
            dist = self._models[mid].success_dist
            score = dist.sample()
            # 在采样值上叠加轻微的均匀噪声，增加探索多样性
            noise = random.uniform(-0.05, 0.05)
            scores[mid] = score + noise

        best = max(scores, key=scores.get)
        self._log_decision("Thompson", scores, best)
        return best

    def _select_ucb(self, available: List[str]) -> str:
        """
        UCB (Upper Confidence Bound):
        score = mean + sqrt(2 * ln(N) / n_i)
        其中 N=总调用数，n_i=模型i的调用数
        """
        N = sum(self._models[mid].total_calls for mid in available)
        scores = {}

        for mid in available:
            stats = self._models[mid]
            mean = stats.success_dist.mean()
            n = stats.total_calls

            if n < self.min_samples:
                # 样本不足时给予探索奖励
                exploration_bonus = self.exploration_weight * math.sqrt(
                    math.log(N + 1) / n
                )
            else:
                exploration_bonus = self.exploration_weight * math.sqrt(
                    math.log(N + 1) / n
                )

            scores[mid] = mean + exploration_bonus

        best = max(scores, key=scores.get)
        self._log_decision("UCB", scores, best)
        return best

    def _select_greedy(self, available: List[str]) -> str:
        """贪心选择：始终选均值最高的"""
        scores = {mid: self._models[mid].success_dist.mean() for mid in available}
        best = max(scores, key=scores.get)
        self._log_decision("Greedy", scores, best)
        return best

    def _select_random(self, available: List[str]) -> str:
        """随机选择（用于冷启动探索）"""
        best = random.choice(available)
        self._log_decision("Random", {mid: 1.0 for mid in available}, best)
        return best

    def _log_decision(self, strategy: str, scores: Dict[str, float], chosen: str):
        self._total_decisions += 1
        if self._total_decisions % 20 == 0:
            debug_info = ", ".join(
                f"{mid}:{v:.3f}" for mid, v in sorted(scores.items(), key=lambda x: -x[1])
            )
            print(f"[BayesianRouter] #{self._total_decisions} [{strategy}] 选择: {chosen} | 评分: {debug_info}")

    def record_result(self, model_id: str, success: bool, latency_ms: float, response: str = ""):
        """记录某模型的调用结果，用于更新后验分布"""
        with self._lock:
            if model_id in self._models:
                self._models[model_id].record_call(success, latency_ms, response)

    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str = None,
        force_model: str = None,
        **kwargs
    ) -> LLMResponse:
        """
        贝叶斯路由的chat接口 (P5-A.2: 返回 LLMResponse)

        Args:
            messages: 对话消息
            model_id: 可选，指定模型ID
            force_model: 可选，强制使用某模型（绕过贝叶斯选择）
            **kwargs: 传递给LLM的参数

        Returns:
            LLMResponse
        """
        if force_model:
            target = force_model
        elif model_id:
            target = model_id
        else:
            target = self.select_model()

        if target not in self._clients:
            # fallback
            available_clients = list(self._clients.keys())
            if not available_clients:
                # P5-B: 记录到 metrics
                get_metrics_collector().record(
                    provider="bayesian", model="router",
                    latency_ms=0.0, success=False, error="no_available_clients",
                )
                return LLMResponse(
                    content="[BayesianRouter] 没有任何可用的LLM客户端",
                    model="bayesian-router",
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    finish_reason="error",
                    error="no_available_clients",
                    request_id=new_trace_id(),
                )
            target = random.choice(available_clients)

        client = self._clients[target]
        trace_id = new_trace_id()
        start = time.time()

        try:
            # 透传 trace_id 到子 client(若有)
            kwargs_with_tid = {**kwargs, "trace_id": trace_id}
            response = client.chat(messages, **kwargs_with_tid)
            latency_ms = round((time.time() - start) * 1000, 2)
            success = self._is_valid_response(response)
            self.record_result(target, success, latency_ms, response.content if hasattr(response, "content") else str(response))
            # 若子 client 已经填了 latency,router 的测量值覆盖(更准,含路由开销)
            try:
                response.latency_ms = latency_ms
                # 保留 router 生成的 trace_id(若子 client 没用就用 router 的)
                if not response.request_id:
                    response.request_id = trace_id
            except Exception:
                pass
            _logger.info(
                "bayesian_route",
                extra={
                    "event": "bayesian_route", "trace_id": trace_id,
                    "provider": "bayesian", "model": target,
                    "latency_ms": latency_ms, "success": success,
                },
            )
            return response
        except Exception as e:
            latency_ms = round((time.time() - start) * 1000, 2)
            self.record_result(target, False, latency_ms, "")
            get_metrics_collector().record(
                provider="bayesian", model=target, latency_ms=latency_ms,
                success=False, error=str(e),
            )
            _logger.warning(
                "bayesian_route_failed",
                extra={
                    "event": "bayesian_route_failed", "trace_id": trace_id,
                    "provider": "bayesian", "model": target,
                    "latency_ms": latency_ms, "error": str(e), "success": False,
                },
            )
            print(f"[BayesianRouter] 模型 {target} 调用异常: {e}")
            return LLMResponse(
                content=f"[错误] 调用失败: {e}",
                model=target,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                finish_reason="error",
                error=str(e),
                latency_ms=latency_ms,
                request_id=trace_id,
            )

    def _is_valid_response(self, response) -> bool:
        """判断响应是否有效 (P5-A.2: 兼容 LLMResponse)"""
        if not response:
            return False
        content = response.content if hasattr(response, "content") else str(response)
        if not content:
            return False
        if hasattr(response, "error") and response.error:
            return False
        invalid_patterns = ["[错误]", "调用失败", "rate limit", "timeout", "exception", "Error"]
        return not any(p.lower() in content.lower() for p in invalid_patterns)

    def get_all_stats(self) -> Dict[str, Any]:
        """获取所有模型的统计信息"""
        with self._lock:
            return {mid: stats.to_dict() for mid, stats in self._models.items()}

    def get_best_model(self) -> str:
        """获取当前最优模型（按均值）"""
        with self._lock:
            if not self._models:
                return "openai"
            return max(
                self._models,
                key=lambda m: self._models[m].success_dist.mean()
            )

    def get_recommendation(self) -> Dict[str, Any]:
        """获取模型推荐和理由"""
        with self._lock:
            best = self.get_best_model()
            best_stats = self._models.get(best)
            if not best_stats:
                return {"recommended": "openai", "reason": "默认推荐"}

            reason_parts = []
            rate = best_stats.success_rate()
            if rate > 0.8:
                reason_parts.append(f"成功率高({rate:.0%})")
            elif rate > 0.5:
                reason_parts.append(f"成功率中等({rate:.0%})")
            else:
                reason_parts.append("作为主要候选")

            if best_stats.avg_latency_ms > 0:
                reason_parts.append(f"平均延迟{best_stats.avg_latency_ms:.0f}ms")

            return {
                "recommended": best,
                "reason": "、".join(reason_parts),
                "stats": best_stats.to_dict()
            }

    def set_strategy(self, strategy: str):
        """动态切换选择策略"""
        valid = {self.STRATEGY_THOMPSON, self.STRATEGY_UCB, self.STRATEGY_GREEDY, self.STRATEGY_RANDOM}
        if strategy not in valid:
            print(f"[BayesianRouter] 无效策略: {strategy}，可用: {valid}")
            return
        self.strategy = strategy
        print(f"[BayesianRouter] 策略切换为: {strategy}")

    def summary(self) -> str:
        """生成路由器的可读摘要"""
        with self._lock:
            lines = [f"[BayesianRouter 摘要] 策略: {self.strategy} | 总决策: {self._total_decisions}"]
            if not self._models:
                return "\n".join(lines) + "\n  (无注册模型)"

            for mid, stats in sorted(self._models.items(), key=lambda x: -x[1].success_dist.mean()):
                mean = stats.success_dist.mean()
                lines.append(
                    f"  {mid}: 调用{stats.total_calls}次 | "
                    f"成功率{stats.success_rate():.1%} | "
                    f"Beta({stats.success_dist.alpha:.1f},{stats.success_dist.beta:.1f}) | "
                    f"延迟{stats.avg_latency_ms:.0f}ms"
                )
            return "\n".join(lines)


class BayesianLLMClient(LLMClient):
    """
    贝叶斯LLM客户端 - 封装 BayesianModelRouter，提供与普通客户端一致的接口

    用法:
        client = BayesianLLMClient()          # 默认 Thompson Sampling
        client = BayesianLLMClient(strategy="ucb")  # 使用 UCB 策略

        # 注册自定义模型
        client.router.register_model("my-gpt4", OpenAIClient(model="gpt-4"), "gpt-4")

        # 正常使用
        response = client.chat([{"role": "user", "content": "你好"}])

        # 查看统计
        print(client.router.summary())
        print(client.router.get_recommendation())
    """

    def __init__(
        self,
        strategy: str = BayesianModelRouter.STRATEGY_THOMPSON,
        exploration_weight: float = 2.0,
        min_samples: int = 3,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.router = BayesianModelRouter(
            strategy=strategy,
            exploration_weight=exploration_weight,
            min_samples=min_samples,
            auto_add_clients=True
        )
        print(f"[OK] 贝叶斯LLM客户端初始化成功 (策略: {strategy})")

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> LLMResponse:
        """P5-A.2: 透传 router.chat() 的 LLMResponse"""
        return self.router.chat(messages, **kwargs)

    def is_available(self) -> bool:
        return len(self.router._clients) > 0

    def set_strategy(self, strategy: str):
        self.router.set_strategy(strategy)

    def get_stats(self) -> Dict:
        return self.router.get_all_stats()

    def summary(self) -> str:
        return self.router.summary()


def create_llm_client(provider: str = "openai", **kwargs) -> LLMClient:
    """
    工厂函数：创建LLM客户端

    Args:
        provider: 提供商 (openai, zhipu, baidu, ali, deepseek, mock, bayesian)
        **kwargs: 其他参数

    Returns:
        LLMClient实例
    """
    if provider == "bayesian":
        strategy = kwargs.pop("strategy", BayesianModelRouter.STRATEGY_THOMPSON)
        exploration_weight = kwargs.pop("exploration_weight", 2.0)
        min_samples = kwargs.pop("min_samples", 3)
        return BayesianLLMClient(
            strategy=strategy,
            exploration_weight=exploration_weight,
            min_samples=min_samples,
            model=kwargs.get("model", "multi"),
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 2000)
        )
    elif provider == "openai":
        return OpenAIClient(**kwargs)
    elif provider == "minimax":
        return MiniMaxClient(**kwargs)
    elif provider == "zhipu":
        return ZhipuClient(**kwargs)
    elif provider == "baidu":
        return BaiduClient(**kwargs)
    elif provider == "ali":
        return AliClient(**kwargs)
    elif provider == "deepseek":
        return DeepSeekClient(**kwargs)
    elif provider == "local":
        print("[WARN]  本地模型支持待实现，使用Mock客户端")
        return MockLLMClient(**kwargs)
    else:
        print(f"[WARN]  未知的LLM provider: {provider}，使用Mock客户端")
        return MockLLMClient(**kwargs)


# 全局LLM客户端实例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取全局LLM客户端"""
    global _llm_client

    if _llm_client is None:
        # 从环境变量读取配置
        provider = os.environ.get("API_PROVIDER", os.environ.get("LLM_PROVIDER", "openai"))
        api_key = os.environ.get("API_KEY", os.environ.get("OPENAI_API_KEY"))
        model = os.environ.get("API_MODEL", os.environ.get("LLM_MODEL", "gpt-4o-mini"))
        temperature = float(os.environ.get("LLM_TEMPERATURE", "0.7"))

        _llm_client = create_llm_client(
            provider=provider,
            api_key=api_key,
            model=model,
            temperature=temperature
        )

    return _llm_client


def get_bayesian_client(
    strategy: str = BayesianModelRouter.STRATEGY_THOMPSON,
    **kwargs
) -> BayesianLLMClient:
    """
    获取贝叶斯路由LLM客户端（便捷函数）

    Args:
        strategy: 选择策略 (thompson, ucb, greedy, random)
        **kwargs: 其他参数传递给 BayesianModelRouter

    Returns:
        BayesianLLMClient实例
    """
    return BayesianLLMClient(
        strategy=strategy,
        exploration_weight=kwargs.get("exploration_weight", 2.0),
        min_samples=kwargs.get("min_samples", 3)
    )


def reset_llm_client():
    """重置LLM客户端（重新初始化）"""
    global _llm_client
    _llm_client = None


# ========== Prompt 模板 ==========

SYSTEM_PROMPT = """你是一个专业、友好的绿色低碳智能助手，名叫"绿宝"。

你的主要职责是：
1. 回答用户关于绿色低碳生活的问题
2. 提供个性化的低碳行动建议
3. 科普环保知识和政策
4. 鼓励和引导用户采取环保行动

回答原则：
- 用词专业但易懂，避免过多术语
- 根据用户的知识水平调整解释深度
- 每次回答尽量提供具体的行动建议
- 语气友善、正向，激励用户而非说教
- 如涉及数据，尽量给出具体数字

记住：你是一个助手，帮助用户更好地理解和实践低碳生活。"""


def build_chat_prompt(
    user_message: str,
    user_profile: Dict[str, Any] = None,
    rag_context: str = None,
    conversation_history: List[Dict] = None,
    working_memory: str = None,
) -> List[Dict[str, str]]:
    """
    构建聊天Prompt

    Args:
        user_message: 用户消息
        user_profile: 用户画像
        rag_context: RAG检索到的上下文
        conversation_history: 对话历史
        working_memory: P4-H 工作记忆 prompt 片段(由 working.snapshot_for_prompt 生成)

    Returns:
        消息列表
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # 添加用户画像上下文
    if user_profile:
        profile_context = _build_profile_context(user_profile)
        if profile_context:
            messages.append({
                "role": "system",
                "content": f"[用户画像]\n{profile_context}"
            })

    # P4-H: 添加工作记忆(P4-H:跨会话 workspace, 主动写)
    if working_memory:
        messages.append({
            "role": "system",
            "content": f"{working_memory}\n\n请结合用户的当前工作记忆上下文(目标/焦点/未完成项)回答。"
        })

    # 添加RAG上下文
    if rag_context:
        messages.append({
            "role": "system",
            "content": f"[参考知识]\n{rag_context}\n\n请结合以上参考知识回答用户问题。"
        })
    
    # 添加对话历史（最近5轮）
    if conversation_history:
        for msg in conversation_history[-10:]:
            role = "user" if msg.get("role") == "user" else "assistant"
            messages.append({
                "role": role,
                "content": msg.get("content", "")[:500]
            })
    
    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})
    
    return messages


def _build_profile_context(profile: Dict[str, Any]) -> str:
    """构建用户画像上下文"""
    parts = []
    
    # 基础信息
    basic = profile.get("basic_info", {})
    if basic:
        parts.append(f"用户年龄段: {basic.get('age_group', '未知')}")
        parts.append(f"所在地区: {basic.get('region', '未知')}")
    
    # 环保画像
    eco = profile.get("eco_profile", {})
    if eco:
        level_map = {
            "beginner": "入门（刚开始了解环保）",
            "intermediate": "了解（有基础环保知识）",
            "advanced": "精通（深度环保实践者）"
        }
        level = level_map.get(eco.get("knowledge_level", ""), eco.get("knowledge_level", "未知"))
        parts.append(f"环保认知水平: {level}")
        
        stage = eco.get("behavior_stage", "意向")
        parts.append(f"行为阶段: {stage}阶段")
        
        interests = eco.get("primary_interests", [])
        if interests:
            parts.append(f"关注领域: {', '.join(interests[:3])}")
    
    # 沟通风格
    comm = profile.get("communication_style", "balanced")
    style_map = {"professional": "专业详细", "simple": "简单易懂", "balanced": "适中"}
    style = style_map.get(comm, comm) if isinstance(comm, str) else "适中"
    parts.append(f"沟通偏好: {style}风格")
    
    return "\n".join(parts) if parts else ""


if __name__ == "__main__":
    print("=" * 60)
    print("LLM客户端测试")
    print("=" * 60)

    # 1. 普通客户端测试
    print("\n[1] 普通LLM客户端")
    client = get_llm_client()
    print(f"LLM客户端状态: {'可用' if client.is_available() else '不可用（使用Mock）'}")

    messages = [
        {"role": "user", "content": "什么是碳中和？"}
    ]

    response = client.chat(messages)
    print(f"\n测试回复:\n{response.content}")

    # 2. 贝叶斯客户端测试
    print("\n" + "=" * 60)
    print("[2] 贝叶斯LLM客户端 (Thompson Sampling)")

    # 方式一：工厂函数
    bayes_client = create_llm_client("bayesian", strategy="thompson")

    # 方式二：直接创建
    # bayes_client = get_bayesian_client(strategy=BayesianModelRouter.STRATEGY_THOMPSON)

    print(f"贝叶斯客户端状态: {'可用' if bayes_client.is_available() else '不可用'}")
    print(f"已注册模型: {list(bayes_client.router._models.keys())}")

    # 模拟多轮调用
    print("\n--- 模拟10轮调用 ---")
    test_questions = [
        "什么是碳中和？",
        "低碳生活有什么建议？",
        "为什么要垃圾分类？",
        "推荐一些环保行动",
        "什么是碳中和？",
        "低碳出行有哪些方式？",
        "为什么要节约用水？",
        "什么是碳达峰？",
        "推荐绿色能源",
        "什么是碳交易？",
    ]

    for i, q in enumerate(test_questions):
        msg = [{"role": "user", "content": q}]
        resp = bayes_client.chat(msg)
        chosen = bayes_client.router.get_recommendation()["recommended"]
        # P5-A.2: resp 是 LLMResponse
        resp_text = resp.content if hasattr(resp, "content") else str(resp)
        print(f"  [{i+1}] Q: {q[:20]}... → 模型: {chosen} → {resp_text[:40]}...")

    print("\n--- 统计摘要 ---")
    print(bayes_client.summary())

    rec = bayes_client.router.get_recommendation()
    print(f"\n推荐模型: {rec['recommended']}")
    print(f"推荐理由: {rec['reason']}")

    # 3. 切换策略测试
    print("\n" + "=" * 60)
    print("[3] 策略切换测试")
    for strat in ["thompson", "ucb", "greedy", "random"]:
        bayes_client.set_strategy(strat)
        selected = bayes_client.router.select_model()
        print(f"  策略 {strat} → 选择模型: {selected}")

    # 4. 所有模型详细统计
    print("\n" + "=" * 60)
    print("[4] 所有模型详细统计")
    stats = bayes_client.get_stats()
    for model_id, s in stats.items():
        print(f"\n  模型: {s['model']} ({s['provider']})")
        print(f"    调用次数: {s['total_calls']} | 成功: {s['success_calls']} | 失败: {s['failed_calls']}")
        print(f"    成功率: {s['success_rate']:.1%} | 平均延迟: {s['avg_latency_ms']:.1f}ms")
        print(f"    Beta分布: alpha={s['success_dist']['alpha']:.2f}, beta={s['success_dist']['beta']:.2f}, mean={s['success_dist']['mean']:.4f}")

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)

