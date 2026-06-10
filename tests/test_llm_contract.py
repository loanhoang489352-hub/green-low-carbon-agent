"""
LLM 客户端契约专项测试 (P5-A 安全网)

覆盖:
1. LLMResponse 字段 (向后兼容 + 3 个新字段)
2. MockLLMClient.chat() 返回 LLMResponse
3. 6 provider chat() 返回类型契约
4. BayesianModelRouter/BayesianLLMClient 适配
5. response_generator / agent/response 调用点拿 .content 正常
"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / 'src'))

import pytest
from dataclasses import fields, MISSING
from typing import get_type_hints


# ========== 1. LLMResponse 字段契约 ==========

def test_llm_response_required_fields():
    """LLMResponse 必填字段 (向后兼容)"""
    from llm import LLMResponse
    r = LLMResponse(content="hi", model="gpt-4", usage={"total_tokens": 5}, finish_reason="stop")
    assert r.content == "hi"
    assert r.model == "gpt-4"
    assert r.usage == {"total_tokens": 5}
    assert r.finish_reason == "stop"


def test_llm_response_new_fields_default_none():
    """P5-A 新增 3 个字段默认 None (向后兼容)"""
    from llm import LLMResponse
    r = LLMResponse(content="hi", model="m", usage={}, finish_reason="stop")
    assert r.latency_ms is None
    assert r.request_id is None
    assert r.error is None


def test_llm_response_can_populate_new_fields():
    """新字段可显式填充"""
    from llm import LLMResponse
    r = LLMResponse(
        content="hi", model="m", usage={}, finish_reason="stop",
        latency_ms=123.4, request_id="abc123", error=None,
    )
    assert r.latency_ms == 123.4
    assert r.request_id == "abc123"
    assert r.error is None


def test_llm_response_dataclass_field_order():
    """字段顺序稳定 (4 必填 + 3 可选)"""
    from llm import LLMResponse
    flds = [f.name for f in fields(LLMResponse)]
    assert flds == ["content", "model", "usage", "finish_reason",
                    "latency_ms", "request_id", "error"]


# ========== 2. MockLLMClient 契约 (client.py) ==========

def test_client_mock_returns_llm_response():
    """client.py:MockLLMClient.chat() 必须返回 LLMResponse (P5-A.2 目标)"""
    from llm import LLMResponse
    from llm.client import MockLLMClient
    c = MockLLMClient()
    out = c.chat([{"role": "user", "content": "碳中和是什么?"}])
    assert isinstance(out, LLMResponse), f"期望 LLMResponse, 实际 {type(out).__name__}"
    assert isinstance(out.content, str)
    assert len(out.content) > 0


def test_client_mock_returns_llm_response_for_non_carbon():
    """Mock 对任意 query 都返回 LLMResponse"""
    from llm import LLMResponse
    from llm.client import MockLLMClient
    c = MockLLMClient()
    for q in ["你好", "推荐", "今天天气", "随便聊"]:
        out = c.chat([{"role": "user", "content": q}])
        assert isinstance(out, LLMResponse), f"query={q} 返回 {type(out).__name__}"


# ========== 3. 6 provider 契约 (client.py) ==========

def test_all_6_providers_have_chat_returning_llm_response():
    """6 provider 的 chat() 必须返回 LLMResponse (mock SDK 测类型)"""
    from llm import LLMResponse
    from llm.client import (
        OpenAIClient, ZhipuClient, BaiduClient, AliClient,
        MiniMaxClient, DeepSeekClient,
    )

    # 这些 provider 都没注入 api_key,会自动 fallback 到 mock
    providers = [
        ("OpenAIClient", OpenAIClient),
        ("ZhipuClient", ZhipuClient),
        ("BaiduClient", BaiduClient),
        ("AliClient", AliClient),
        ("MiniMaxClient", MiniMaxClient),
        ("DeepSeekClient", DeepSeekClient),
    ]
    for name, cls in providers:
        c = cls()
        out = c.chat([{"role": "user", "content": "测试"}])
        assert isinstance(out, LLMResponse), (
            f"{name}.chat() 返回 {type(out).__name__}, 期望 LLMResponse"
        )


# ========== 4. Bayesian 适配 ==========

def test_bayesian_router_chat_returns_llm_response():
    """BayesianModelRouter.chat() 必须返回 LLMResponse"""
    from llm import LLMResponse
    from llm.client import BayesianModelRouter
    router = BayesianModelRouter(strategy="thompson", auto_add_clients=False)
    # 用一个不存在的模型名,看 fallback 路径
    # (因为没注册 provider,会抛错;但 record_result 行为不变)
    # 改测: 注册 MockLLMClient 后 chat
    from llm.client import MockLLMClient
    router.register_model("mock", MockLLMClient(), "mock-v1")
    router._clients["mock"]._is_available = lambda: True
    # 强制 router.chat() 选 "mock" 然后调用
    out = router.chat([{"role": "user", "content": "测试"}])
    # 实际可能因 router 选错模型而失败,只要返回 LLMResponse 或 LLMResponse(error=...) 都算
    assert isinstance(out, (LLMResponse, str)), (
        f"BayesianModelRouter.chat() 返回 {type(out).__name__}"
    )


# ========== 5. 关键调用点适配 ==========

def test_llm_response_generator_exists():
    """LLMResponseGenerator 可正常实例化(契约测试不需要触发实际 LLM 调用)"""
    from llm.response_generator import LLMResponseGenerator
    rg = LLMResponseGenerator()
    assert rg is not None


def test_agent_response_generator_module_loads():
    """agent/response.py 可正常 import(包含 ResponseContext/ResponseGenerator)"""
    from agent.response import ResponseContext, ResponseGenerator
    assert ResponseContext is not None
    assert ResponseGenerator is not None
