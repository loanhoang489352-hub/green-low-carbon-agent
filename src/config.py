"""
统一环境配置
集中所有环境变量解析,避免散落在各模块
"""
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


@dataclass
class LLMConfig:
    provider: str = field(default_factory=lambda: os.environ.get("API_PROVIDER", "openai"))
    model: str = field(default_factory=lambda: os.environ.get("API_MODEL", "gpt-4o-mini"))
    temperature: float = field(default_factory=lambda: float(os.environ.get("LLM_TEMPERATURE", "0.7")))
    timeout_seconds: float = field(default_factory=lambda: float(os.environ.get("LLM_TIMEOUT_SECONDS", "30")))
    max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 2))
    insecure_skip_verify: bool = field(default_factory=lambda: _env_bool("INSECURE_SKIP_VERIFY", False))


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
    metrics_history_size: int = field(default_factory=lambda: _env_int("METRICS_HISTORY_SIZE", 1000))


@dataclass
class RAGConfig:
    embedding_model: str = field(
        default_factory=lambda: os.environ.get("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
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


def get_settings() -> Settings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """重置(仅供测试)"""
    global _settings
    _settings = None
