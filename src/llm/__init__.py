"""
LLM 模块 - 提供大语言模型调用能力
支持 OpenAI API 和本地模型
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

# P5-F: 模块级 logger
try:
    from observability import get_logger
    _logger = get_logger("llm")
except Exception:
    import logging
    _logger = logging.getLogger("llm")


# ========== P6.G: LLM_MOCK 开关 ==========
# LLM_MOCK=true  → 强制走 mock(即使 API key 已配好,也不调真实 API)
# LLM_MOCK=false → 强制真实 API
# LLM_MOCK=auto  → 默认(client 未配时 mock,配了真调)
#
# 用法:  pytest / dev / CI    →  LLM_MOCK=true python main.py
#       生产                   →  LLM_MOCK=false(或 unset)
#       单元测试              →  LLM_MOCK=true pytest
# 价值:
#   - 单元测试不依赖真实 API(稳定 + 0 成本)
#   - 开发时不烧 API 配额
#   - CI 跑全量测试不卡
#   - 同一份代码 + 不同 env = 不同行为

LLM_MOCK_VALUES = {"true", "false", "auto", "1", "0", "yes", "no", "on", "off", ""}


def is_mock_mode() -> bool:
    """
    P6.G: 检查是否处于 mock 模式

    规则:
      LLM_MOCK=true/1/yes/on  → True
      LLM_MOCK=false/0/no/off → False(强制真实 API,即使 client 没配也会失败)
      LLM_MOCK=auto / 未设      → 取决于客户端是否配好(client None 时 mock,否则真调)
    """
    val = os.environ.get("LLM_MOCK", "auto").strip().lower()
    if val in ("true", "1", "yes", "on"):
        return True
    if val in ("false", "0", "no", "off"):
        return False
    return None  # auto


def should_use_mock(client) -> bool:
    """
    P6.G: 决定 chat() 是否走 mock 路径

    参数:
        client: LLM client 实例
        (检查 .client / ._client / ._access_token 任一字段是否为 None)
    """
    mock_mode = is_mock_mode()
    if mock_mode is True:
        return True
    if mock_mode is False:
        return False
    # auto: 检查常见"配置"字段
    for attr in ("client", "_client", "_access_token"):
        inner = getattr(client, attr, None)
        if inner is not None:
            return False
    return True  # 全 None → mock


def log_mock_decision(provider: str, used_mock: bool) -> None:
    """记录 mock 决策(便于诊断)"""
    val = os.environ.get("LLM_MOCK", "auto")
    _logger.info(
        "[LLM] provider=%s mock_mode=%s used_mock=%s",
        provider, val, used_mock,
    )

# Windows UTF-8 encoding setup - only if not already done
if sys.platform == 'win32' and hasattr(sys.stdout, 'buffer'):
    try:
        if sys.stdout.encoding != 'utf-8' or not isinstance(sys.stdout, io.TextIOWrapper):
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


@dataclass
class LLMResponse:
    """LLM响应 (P5-A 统一契约)
    - content: 文本内容
    - model: 实际使用的模型
    - usage: token 用量 {prompt_tokens, completion_tokens, total_tokens}
    - finish_reason: 完成原因 (stop/length/error)
    - latency_ms: 调用耗时(P5-A 新增,P5-B trace_id 联动)
    - request_id: 链路追踪 ID(P5-A 新增,P5-B 自动注入)
    - error: 错误信息(成功时为空,P5-C 错误处理使用)
    """
    content: str
    model: str
    usage: Dict[str, int]
    finish_reason: str
    latency_ms: Optional[float] = None
    request_id: Optional[str] = None
    error: Optional[str] = None


class LLMClient:
    """LLM客户端基类"""
    
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.7, max_tokens: int = 1000):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def generate(self, prompt: str, system_prompt: str = None) -> LLMResponse:
        """生成文本"""
        raise NotImplementedError
    
    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """聊天"""
        raise NotImplementedError


class OpenAIClient(LLMClient):
    """OpenAI API 客户端"""
    
    def __init__(
        self,
        api_key: str = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 1000
    ):
        super().__init__(model, temperature, max_tokens)

        # 从环境变量或配置文件获取 API Key
        if api_key is None:
            api_key = os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY", "")

        self.api_key = api_key
        self.client = None
        self._initialized = False

        # 只要有有效的 API Key 就初始化
        if self.api_key and self.api_key not in ("", "your_api_key_here"):
            self._initialize_client()
    
    def _initialize_client(self):
        """初始化 OpenAI 客户端"""
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
            self._initialized = True
            print(f"[OK] OpenAI 客户端初始化成功 (模型: {self.model})")
        except ImportError:
            _logger.warning("openai 包未安装,将使用 Mock 模式")
            self.client = None
        except Exception as e:
            _logger.warning(f"OpenAI 客户端初始化失败: {e}")
            self.client = None

    def is_available(self) -> bool:
        """检查客户端是否可用"""
        return self.client is not None
    
    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """发送聊天请求"""
        # P6.G: LLM_MOCK 开关(强 mock)
        if should_use_mock(self):
            log_mock_decision("OpenAI", True)
            return self._mock_response(messages)
        # auto + client 未配 → mock(原行为)
        if self.client is None:
            return self._mock_response(messages)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            return LLMResponse(
                content=response.choices[0].message.content,
                model=response.model,
                usage={
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                    "total_tokens": response.usage.total_tokens
                },
                finish_reason=response.choices[0].finish_reason
            )
        except Exception as e:
            print(f"[ERR] OpenAI API 调用失败: {e}")
            return self._mock_response(messages)
    
    def generate(self, prompt: str, system_prompt: str = None) -> LLMResponse:
        """生成文本"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages)
    
    def _mock_response(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """Mock 响应（当 API 不可用时）"""
        last_message = messages[-1]["content"] if messages else ""
        
        mock_content = f"""[这是Mock响应] 感谢你的提问！

我收到了你的消息: "{last_message[:50]}..."

由于当前使用的是演示模式，完整的AI对话功能需要配置有效的OpenAI API Key。

请确保:
1. 在 .env 文件中设置了有效的 OPENAI_API_KEY
2. 已安装 openai 包: pip install openai

如果你已经配置好，可以通过API继续使用AI增强的对话体验！
"""
        
        return LLMResponse(
            content=mock_content,
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop"
        )


class MockLLMClient(LLMClient):
    """Mock LLM 客户端（用于测试）"""
    
    def __init__(self, model: str = "mock", temperature: float = 0.7, max_tokens: int = 1000):
        super().__init__(model, temperature, max_tokens)
    
    def generate(self, prompt: str, system_prompt: str = None) -> LLMResponse:
        """生成 Mock 响应"""
        return self._create_response(prompt, system_prompt)
    
    def chat(self, messages: List[Dict[str, str]]) -> LLMResponse:
        """生成 Mock 响应"""
        last_message = messages[-1]["content"] if messages else ""
        return self._create_response(last_message)
    
    def _create_response(self, user_input: str, system_prompt: str = None) -> LLMResponse:
        """创建 Mock 响应"""
        return LLMResponse(
            content=f"[Mock模式] 收到了: {user_input[:100]}...",
            model="mock",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            finish_reason="stop"
        )


def create_llm_client(
    provider: str = "openai",
    model: str = "gpt-4o-mini",
    api_key: str = None,
    temperature: float = 0.7,
    max_tokens: int = 1000
) -> LLMClient:
    """
    工厂函数：创建 LLM 客户端

    Args:
        provider: 提供商 ("openai", "minimax", "zhipu", "baidu", "ali", "deepseek", "mock")
        model: 模型名称
        api_key: API Key
        temperature: 温度参数
        max_tokens: 最大 token 数

    Returns:
        LLMClient 实例
    """
    if provider == "openai":
        return OpenAIClient(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
    elif provider == "minimax":
        from llm.client import MiniMaxClient
        return MiniMaxClient(api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
    elif provider == "zhipu":
        from llm.client import ZhipuClient
        return ZhipuClient(api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
    elif provider == "baidu":
        from llm.client import BaiduClient
        return BaiduClient(api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
    elif provider == "ali":
        from llm.client import AliClient
        return AliClient(api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
    elif provider == "deepseek":
        from llm.client import DeepSeekClient
        return DeepSeekClient(api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens)
    elif provider == "mock":
        return MockLLMClient(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )
    else:
        _logger.warning(f"不支持的 LLM 提供商: {provider},使用 Mock 模式")
        return MockLLMClient(model=model)


# 系统提示词模板
SYSTEM_PROMPT_TEMPLATE = """你是一个专业的绿色低碳智能助手，名为"绿宝"。

你的职责：
1. 帮助用户了解碳中和、节能减排等环保知识
2. 根据用户情况提供个性化的低碳生活建议
3. 引导用户采取实际行动，减少碳排放
4. 回答关于环保政策、绿色产品等问题

用户信息：
- 环保认知水平：{knowledge_level}
- 行为阶段：{behavior_stage}
- 关注领域：{interests}
- 沟通风格：{communication_style}

本轮建议策略（P4-D 行为阶段驱动）：
- 焦点：{focus}
- 建议强度：{suggestion_intensity}
- 行动复杂度：{action_complexity}
- 语气：{tone}
- 示例侧重：{example_focus}

回复要求：
1. 使用友好、鼓励的语气
2. 根据用户认知水平调整解释深度
3. 每条建议尽量具体可执行
4. 可以适当引用数据和事实
5. 回答控制在200-300字左右
6. 严格遵循"行为阶段策略":在"无意向"阶段避免激进建议
   在"准备/行动"阶段提供可执行步骤
7. 示例选择需符合"示例侧重"({example_focus})
"""


def build_system_prompt(personalization_ctx: Dict[str, Any]) -> str:
    """构建系统提示词(P4-D 扩展:把行为阶段策略注入 prompt)"""
    knowledge_level = personalization_ctx.get("knowledge_level_chinese", "了解")
    behavior_stage = personalization_ctx.get("behavior_stage", "意向")
    interests = personalization_ctx.get("confirmed_interests", personalization_ctx.get("primary_interests", []))
    if isinstance(interests, list):
        interests = "、".join(interests[:3]) if interests else "绿色生活"
    communication_style = personalization_ctx.get("communication_style", "平衡")

    # P4-D: 行为阶段驱动的策略变量
    focus = personalization_ctx.get("focus", "意识唤醒")
    suggestion_intensity = personalization_ctx.get("suggestion_intensity", "low")
    action_complexity = personalization_ctx.get("action_complexity", "simple")
    tone = personalization_ctx.get("tone", "positive")
    example_focus = personalization_ctx.get("example_focus", "similar_people")

    return SYSTEM_PROMPT_TEMPLATE.format(
        knowledge_level=knowledge_level,
        behavior_stage=behavior_stage,
        interests=interests,
        communication_style=communication_style,
        focus=focus,
        suggestion_intensity=suggestion_intensity,
        action_complexity=action_complexity,
        tone=tone,
        example_focus=example_focus,
    )


def build_conversation_prompt(
    user_message: str,
    rag_context: str = "",
    conversation_history: List[Dict] = None,
    personalization_ctx: Dict[str, Any] = None
) -> List[Dict[str, str]]:
    """构建对话消息列表"""
    messages = []
    
    # 系统提示词
    if personalization_ctx:
        system_prompt = build_system_prompt(personalization_ctx)
    else:
        system_prompt = """你是一个专业的绿色低碳智能助手，帮助用户了解环保知识、提供低碳生活建议。"""
    
    messages.append({"role": "system", "content": system_prompt})
    
    # 对话历史
    if conversation_history:
        for msg in conversation_history[-6:]:  # 最近3轮对话
            role = "assistant" if msg.get("role") == "assistant" else "user"
            messages.append({
                "role": role,
                "content": msg.get("content", "")
            })
    
    # RAG 上下文
    if rag_context:
        context_msg = f"""[参考知识]
{rag_context}

[问题]
{user_message}"""
        messages.append({"role": "user", "content": context_msg})
    else:
        messages.append({"role": "user", "content": user_message})
    
    return messages


# 全局客户端实例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取全局 LLM 客户端

    P6.S.5 智能 fallback:
    1. LLM_MOCK=true → 强制 MockLLMClient(跳真实 API)
    2. 配置的 provider 没 API key → 自动 MockLLMClient(避免 401)
    3. 否则用真实 API 客户端
    """
    global _llm_client
    if _llm_client is None:
        # P6.S.5: LLM_MOCK=true 强制 mock
        if os.getenv("LLM_MOCK", "auto").strip().lower() in ("true", "1", "yes", "on"):
            from llm.client import MockLLMClient
            _llm_client = MockLLMClient()
            print("[LLM] LLM_MOCK=true → 强制 MockLLMClient(跳过真实 API)")
            return _llm_client

        provider = os.getenv("API_PROVIDER", "openai")
        model = os.getenv("API_MODEL", "gpt-4o-mini")
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))

        # 根据不同的提供商读取正确的环境变量
        provider_key_map = {
            "openai": os.getenv("OPENAI_API_KEY") or os.getenv("API_KEY"),
            "minimax": os.getenv("MINIMAX_API_KEY") or os.getenv("API_KEY"),
            "zhipu": os.getenv("ZHIPU_API_KEY") or os.getenv("API_KEY"),
            "baidu": os.getenv("BAIDU_API_KEY") or os.getenv("API_KEY"),
            "ali": os.getenv("ALI_API_KEY") or os.getenv("API_KEY"),
            "deepseek": os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY"),
        }
        api_key = provider_key_map.get(provider) or os.getenv("API_KEY")

        # P6.S.5: 关键 — 没 API key 自动降级 MockLLMClient,避免 401
        if not api_key or api_key.startswith("__SET_ME__") or api_key in ("sk-your-api-key-here", "your-api-key"):
            from llm.client import MockLLMClient
            print(f"[LLM] provider={provider} 没有效 API key → 自动 MockLLMClient")
            _llm_client = MockLLMClient()
            return _llm_client

        print(f"[LLM] 初始化客户端: provider={provider}, model={model}, has_key=({'是' if api_key else '否'})")

        _llm_client = create_llm_client(
            provider=provider,
            api_key=api_key,
            model=model,
            temperature=temperature
        )

    return _llm_client


def reset_llm_client():
    """重置LLM客户端（重新初始化）"""
    global _llm_client
    _llm_client = None


def set_llm_client(client: LLMClient):
    """设置全局 LLM 客户端"""
    global _llm_client
    _llm_client = client


# 导出 build_chat_prompt
from llm.client import build_chat_prompt

__all__ = [
    'LLMClient', 'LLMResponse', 'OpenAIClient', 'MockLLMClient',
    'create_llm_client', 'get_llm_client', 'reset_llm_client', 'set_llm_client',
    'build_chat_prompt', 'build_system_prompt', 'build_conversation_prompt',
    'SYSTEM_PROMPT_TEMPLATE'
]
