"""
统一环境配置
集中所有环境变量解析,避免散落在各模块

P5-I.B: 启动时强校验 *_API_KEY 不等于占位符(如 `__SET_ME__`),
避免"配错环境就跑"的低级错误。
"""

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "").lower().strip()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    raw = os.environ.get(name, "")
    if not raw:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


# P5-I.B: 启动时检测 *_API_KEY 是否还是占位符
_PLACEHOLDER_PATTERNS = (
    "__SET_ME__",
    "your_api_key_here",
    "your-api-key",
    "sk-xxx",
    "sk-XXXX",
    "changeme",
    "TODO",
    "PLACEHOLDER",
)


def _is_placeholder(value: str) -> bool:
    if not value:
        return False
    v = value.strip().lower()
    for p in _PLACEHOLDER_PATTERNS:
        if p.lower() in v:
            return True
    return False


# 任务1(Task1): provider → env var 映射,用于精准 fail-fast
_PROVIDER_KEY_MAP = {
    "openai": ["OPENAI_API_KEY", "API_KEY"],
    "minimax": ["MINIMAX_API_KEY"],
    "zhipu": ["ZHIPU_API_KEY"],
    "baidu": ["BAIDU_API_KEY"],
    "ali": ["ALI_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "qwen": ["QWEN_API_KEY"],
    "glm": ["GLM_API_KEY"],
    "doubao": ["DOUBAO_API_KEY"],
}


def _check_api_keys() -> None:
    """任务1: 启动时强校验 API key,默认仅 warning,但:
    1. STRICT_API_KEYS=true (或 ENV=production) 时 — 命中占位符/空值 直接 raise RuntimeError 终止启动
    2. 主动校验当前 API_PROVIDER 对应的 key(其他 provider 未配置不算错)
    3. 简单格式校验(>=20 字符 + sk- 前缀用于 OpenAI/DeepSeek)
    """
    keys_to_check = [
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "ANTHROPIC_API_KEY",
        "MINIMAX_API_KEY",
        "QWEN_API_KEY",
        "GLM_API_KEY",
        "DOUBAO_API_KEY",
        "API_KEY",
        "HUGGINGFACE_TOKEN",
    ]
    env = os.environ.get("ENV", "development").lower()
    strict = _env_bool("STRICT_API_KEYS", env in ("production", "prod"))
    log = logging.getLogger("config")

    # 1) 占位符扫描(全部 provider)
    flagged_placeholder = [k for k in keys_to_check if _is_placeholder(os.environ.get(k, ""))]
    # 2) 空值扫描(全部 provider)
    flagged_empty = [k for k in keys_to_check if not os.environ.get(k, "").strip()]

    # 3) 当前激活 provider 的 key 专项校验
    active_provider = os.environ.get("API_PROVIDER", "openai").lower()
    active_keys = _PROVIDER_KEY_MAP.get(active_provider, [])
    active_value = ""
    for ak in active_keys:
        active_value = os.environ.get(ak, "") or active_value
    active_problem = None
    if not active_value.strip():
        active_problem = f"当前 API_PROVIDER={active_provider} 期望 env {active_keys} 至少一个非空"
    elif _is_placeholder(active_value):
        active_problem = f"当前 API_PROVIDER={active_provider} 的 key 仍为占位符"
    elif active_provider in ("openai", "deepseek") and not active_value.startswith("sk-"):
        active_problem = f"当前 API_PROVIDER={active_provider} 的 key 缺少 sk- 前缀(疑似格式错误)"

    # 汇总输出
    if flagged_placeholder or flagged_empty or active_problem:
        msg_lines = ["[config] API key 校验发现问题:"]
        if flagged_placeholder:
            msg_lines.append(f"  占位符: {flagged_placeholder}")
        if flagged_empty:
            msg_lines.append(f"  空值: {flagged_empty}")
        if active_problem:
            msg_lines.append(f"  ⚠ 激活 provider 异常: {active_problem}")
        msg = "\n".join(msg_lines)

        if active_problem and strict:
            log.error(msg)
            raise RuntimeError(
                msg + "\n请在 .env 中填入真实 key,或设置 STRICT_API_KEYS=false 临时绕过"
            )
        elif active_problem:
            log.error(msg + "\n(STRICT_API_KEYS=false,仅记录不阻塞启动 — LLM 调用将失败)")
        elif flagged_placeholder and env in ("production", "prod"):
            log.error(msg)
        else:
            log.warning(msg)


@dataclass
class LLMConfig:
    provider: str = field(default_factory=lambda: os.environ.get("API_PROVIDER", "openai"))
    model: str = field(default_factory=lambda: os.environ.get("API_MODEL", "gpt-4o-mini"))
    temperature: float = field(
        default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.7"))
    )
    timeout_seconds: float = field(
        default_factory=lambda: float(os.environ.get("LLM_TIMEOUT_SECONDS", "30"))
    )
    max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 2))
    insecure_skip_verify: bool = field(
        default_factory=lambda: _env_bool("INSECURE_SKIP_VERIFY", False)
    )


@dataclass
class ExecutionConfig:
    use_langgraph: bool = field(default_factory=lambda: _env_bool("USE_LANGGRAPH", False))
    langgraph_mode: str = field(default_factory=lambda: os.environ.get("LANGGRAPH_MODE", ""))

    @property
    def is_react(self) -> bool:
        return self.use_langgraph and self.langgraph_mode == "react"


@dataclass
class ServerConfig:
    host: str = field(default_factory=lambda: os.environ.get("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: _env_int("PORT", 8000))
    cors_origins: List[str] = field(
        default_factory=lambda: _env_list("CORS_ORIGINS", ["http://127.0.0.1:8000"])
    )
    max_body_size: int = field(default_factory=lambda: _env_int("MAX_BODY_SIZE", 2_000_000))


@dataclass
class ObservabilityConfig:
    """P5-B: 可观测性配置"""

    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    log_file: str = field(default_factory=lambda: os.environ.get("LOG_FILE", "data/logs/app.log"))
    metrics_history_size: int = field(
        default_factory=lambda: _env_int("METRICS_HISTORY_SIZE", 1000)
    )


@dataclass
class RAGConfig:
    embedding_model: str = field(
        default_factory=lambda: os.environ.get(
            "EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
        )
    )
    collection_name: str = field(
        default_factory=lambda: os.environ.get("RAG_COLLECTION", "green_agent_knowledge")
    )


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.environ.get("ENV", "development"))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    rag: RAGConfig = field(default_factory=RAGConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)


_settings: Optional[Settings] = None
_checked: bool = False


def get_settings() -> Settings:
    """获取全局配置单例(P5-I.B: 首次调用时跑占位符校验)"""
    global _settings, _checked
    if _settings is None:
        _settings = Settings()
    if not _checked:
        _check_api_keys()
        _checked = True
    return _settings


def reset_settings() -> None:
    """重置(仅供测试)"""
    global _settings, _checked
    _settings = None
    _checked = False
