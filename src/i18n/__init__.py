"""
i18n 模块 — P6.H

中英双语错误消息 + 系统提示。简单 dict 实现,无 gettext 依赖。

用法:
    from i18n import t, get_locale, set_locale

    # 字符串翻译
    t("error.unauthorized", locale="zh")  # → "需要登录"
    t("error.unauthorized", locale="en")  # → "Authentication required"

    # 全局 locale(默认 zh)
    set_locale("en")
    t("error.unauthorized")  # → "Authentication required"

    # 头检测(从 Accept-Language 解析)
    locale = get_locale_from_header("en-US,zh-CN;q=0.9")  # → "en"
"""
from __future__ import annotations

import os
import threading
from typing import Optional

# 支持的 locale(zh-CN 默认)
SUPPORTED_LOCALES = ("zh", "en")
DEFAULT_LOCALE = "zh"

# 全局 locale(thread-local,因为多请求可能不同)
_locale = threading.local()


def set_locale(locale: str) -> None:
    """设置当前线程的 locale(线程级)"""
    locale = locale.lower().split("-")[0]  # zh-CN → zh
    if locale not in SUPPORTED_LOCALES:
        locale = DEFAULT_LOCALE
    _locale.value = locale


def get_locale() -> str:
    """获取当前线程的 locale"""
    val = getattr(_locale, "value", None)
    if val is None:
        # 读 env var LANG / LC_ALL
        env = os.environ.get("LANG", "").lower()
        if env.startswith("en"):
            val = "en"
        else:
            val = DEFAULT_LOCALE
    return val


def get_locale_from_header(accept_language: Optional[str]) -> str:
    """从 Accept-Language 头解析最匹配的 locale(按 q 权重)

    例: "en-US,zh-CN;q=0.9" → "en" (q=1.0 默认)
        "zh-CN,en;q=0.8"   → "zh" (zh 排前)
        "fr,de"             → 默认 (不支持)
    """
    if not accept_language:
        return get_locale()
    # 解析:每个 entry = locale[,q=value]
    entries = []
    for part in accept_language.lower().split(","):
        part = part.strip()
        if not part:
            continue
        loc_part = part.split(";")[0].strip()
        # 标准化:zh-CN → zh
        loc = loc_part.split("-")[0].strip()
        q = 1.0
        for kv in part.split(";")[1:]:
            kv = kv.strip()
            if kv.startswith("q="):
                try:
                    q = float(kv[2:])
                except ValueError:
                    q = 1.0
        entries.append((loc, q))
    # 按 q 降序,取第一个在 SUPPORTED_LOCALES 里的
    entries.sort(key=lambda x: -x[1])
    for loc, _ in entries:
        if loc in SUPPORTED_LOCALES:
            return loc
    return get_locale()


# ========== 翻译字典 ==========

TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh": {
        # 通用错误
        "error.unauthorized": "需要登录",
        "error.forbidden": "没有权限",
        "error.not_found": "资源不存在",
        "error.bad_request": "请求参数错误",
        "error.internal": "服务暂时不可用",
        "error.rate_limited": "请求过于频繁",
        "error.llm_unavailable": "LLM 服务暂不可用",
        "error.validation": "输入校验失败",

        # 健康检查
        "health.ok": "正常",
        "health.degraded": "降级",
        "health.down": "宕机",
        "health.check.accounts_db": "账号数据库",
        "health.check.vector_store": "向量数据库",
        "health.check.scheduler": "调度器",
        "health.check.metrics": "LLM 指标",
        "health.check.disk_space": "磁盘空间",

        # 系统提示词片段
        "prompt.system.role": "你是绿色低碳智能体,一个专注于帮助用户实践低碳生活的助手。",
        "prompt.user_focus": "关注用户当前关心的环保话题",
        "prompt.carbon_saving": "优先推荐碳减排效果明显的行动",

        # 行为阶段
        "stage.no_intent": "无意向",
        "stage.intent": "意向",
        "stage.preparation": "准备",
        "stage.action": "行动",
        "stage.maintenance": "维持",

        # Web UI
        "ui.title": "绿色低碳智能体",
        "ui.chat_placeholder": "请输入您想了解的环保话题...",
        "ui.send": "发送",
        "ui.thinking": "思考中...",
        "ui.locale_switch": "语言",
    },
    "en": {
        # 通用错误
        "error.unauthorized": "Authentication required",
        "error.forbidden": "Permission denied",
        "error.not_found": "Resource not found",
        "error.bad_request": "Bad request parameters",
        "error.internal": "Service temporarily unavailable",
        "error.rate_limited": "Too many requests",
        "error.llm_unavailable": "LLM service unavailable",
        "error.validation": "Validation failed",

        # 健康检查
        "health.ok": "OK",
        "health.degraded": "Degraded",
        "health.down": "Down",
        "health.check.accounts_db": "Accounts DB",
        "health.check.vector_store": "Vector Store",
        "health.check.scheduler": "Scheduler",
        "health.check.metrics": "LLM Metrics",
        "health.check.disk_space": "Disk Space",

        # 系统提示词片段
        "prompt.system.role": "You are the Green Low-Carbon Agent, a helpful assistant focused on low-carbon lifestyle.",
        "prompt.user_focus": "Focus on user's current environmental concern",
        "prompt.carbon_saving": "Prioritize actions with significant carbon reduction",

        # 行为阶段
        "stage.no_intent": "No Intent",
        "stage.intent": "Intent",
        "stage.preparation": "Preparation",
        "stage.action": "Action",
        "stage.maintenance": "Maintenance",

        # Web UI
        "ui.title": "Green Low-Carbon Agent",
        "ui.chat_placeholder": "Ask about environmental topics...",
        "ui.send": "Send",
        "ui.thinking": "Thinking...",
        "ui.locale_switch": "Language",
    },
}


def t(key: str, locale: Optional[str] = None, **kwargs) -> str:
    """
    翻译 key(返回当前 locale 对应字符串)

    参数:
        key: 翻译 key(例 "error.unauthorized")
        locale: 显式指定 locale(默认用 get_locale())
        **kwargs: 格式化参数(例 t("greeting", name="Alice") → "Hello Alice")
    """
    loc = locale or get_locale()
    if loc not in TRANSLATIONS:
        loc = DEFAULT_LOCALE
    text = TRANSLATIONS[loc].get(key)
    if text is None:
        # fallback 到默认 locale
        text = TRANSLATIONS[DEFAULT_LOCALE].get(key, f"[{key}]")
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def list_keys() -> list[str]:
    """列出所有翻译 key(测试 / 文档用)"""
    return sorted(set(TRANSLATIONS["zh"].keys()) | set(TRANSLATIONS["en"].keys()))


__all__ = [
    "SUPPORTED_LOCALES",
    "DEFAULT_LOCALE",
    "set_locale",
    "get_locale",
    "get_locale_from_header",
    "t",
    "list_keys",
    "TRANSLATIONS",
]
