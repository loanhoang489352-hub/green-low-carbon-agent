"""
统一错误响应 + APIError 异常类 (P5-E + P6.H i18n)

设计:
- APIError 携带 code + message + status,handler 抛出后 _dispatch 捕获并转 JSON
- 未知异常被 _dispatch 兜底,traceback 写日志,客户端只看到 INTERNAL
- error_response() 构造标准 JSON 响应(向后兼容)
- HTTP_STATUS_MAP 是 code → (status, default_message) 查找表
- P6.H: 错误消息支持中英双语,根据 Accept-Language 头或 thread-local locale 切换
"""

from typing import Any, Dict, Optional, Tuple


def _i18n_message(code: str) -> str:
    """P6.H: 根据当前 locale 返错误消息(默认中文)"""
    try:
        from i18n import t

        # 把错误码映射到 i18n key
        key = f"error.{code.lower()}"
        return t(key) if t(key) != f"[{key}]" else None
    except Exception:
        return None


# ========== 错误码 → HTTP 状态映射 ==========

# (status, 中文默认 message, 英文默认 message)
# P6.H: 加英文 message 列,locale=en 时用英文
_HTTP_STATUS_DATA: Dict[str, Tuple[int, str, str]] = {
    # 4xx
    "BAD_REQUEST": (400, "请求参数错误", "Invalid request"),
    "UNAUTHORIZED": (401, "需要登录", "Authentication required"),
    "FORBIDDEN": (403, "没有权限", "Permission denied"),
    "NOT_FOUND": (404, "资源不存在", "Resource not found"),
    "METHOD_NOT_ALLOWED": (405, "方法不允许", "Method not allowed"),
    "CONFLICT": (409, "资源冲突", "Resource conflict"),
    "BODY_TOO_LARGE": (413, "请求体过大", "Request body too large"),
    "RATE_LIMITED": (429, "请求过于频繁", "Too many requests"),
    "VALIDATION": (422, "输入校验失败", "Validation failed"),
    # 5xx
    "INTERNAL": (500, "服务暂时不可用", "Service temporarily unavailable"),
    "NOT_IMPLEMENTED": (501, "未实现", "Not implemented"),
    "LLM_UNAVAILABLE": (503, "LLM 暂不可用", "LLM temporarily unavailable"),
    "DEPENDENCY_DOWN": (503, "依赖服务不可用", "Dependency unavailable"),
    "TIMEOUT": (504, "请求超时", "Request timeout"),
}


def status_for(code: str, default: int = 500) -> int:
    """code → HTTP 状态码,未注册则返 default"""
    return _HTTP_STATUS_DATA.get(code, (default, "", ""))[0]


def message_for(code: str, locale: Optional[str] = None) -> str:
    """code → 默认 message(P6.H: 按 locale 选 zh/en)

    locale: None=用当前 thread-local locale, "zh"/"en" 显式指定
    """
    entry = _HTTP_STATUS_DATA.get(code)
    if entry is None:
        return "Unknown error" if (locale or "zh") == "en" else "未知错误"
    _status, msg_zh, msg_en = entry
    if locale is None:
        try:
            from i18n import get_locale

            locale = get_locale()
        except Exception:
            locale = "zh"
    return msg_en if locale == "en" else msg_zh


# ========== APIError 异常类 ==========


class APIError(Exception):
    """
    P5-E: 业务异常 — 携带错误码,handler 抛出后由 _dispatch 捕获并转 JSON 响应
    P6.H: 支持 locale(message 按 Accept-Language 切换)

    用法:
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        if not authorized:
            raise APIError("FORBIDDEN", "无权访问此资源")
        if llm_down:
            raise APIError("LLM_UNAVAILABLE", "所有 LLM provider 失败")
    """

    def __init__(
        self,
        code: str,
        message: Optional[str] = None,
        status: Optional[int] = None,
        locale: Optional[str] = None,
        **extra: Any,
    ):
        self.code = code
        self.locale = locale
        if message:
            self.message = message
        else:
            self.message = message_for(code, locale=locale)
        self.status = status or status_for(code)
        self.extra = extra
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "status": self.status,
            },
        }
        if self.extra:
            payload["error"].update(self.extra)
        return payload


# ========== 向后兼容的 error_response() ==========


def error_response(code: str, message: str, status: int = 400, **extra: Any) -> Dict[str, Any]:
    """构造标准错误响应(P2 兼容,handler 内可用 send_json(error_response(...), status=...))"""
    payload: Dict[str, Any] = {"error": {"code": code, "message": message, "status": status}}
    if extra:
        payload["error"].update(extra)
    return payload


COMMON_ERRORS = {
    400: error_response("BAD_REQUEST", message_for("BAD_REQUEST")),
    401: error_response("UNAUTHORIZED", message_for("UNAUTHORIZED"), status=401),
    403: error_response("FORBIDDEN", message_for("FORBIDDEN"), status=403),
    404: error_response("NOT_FOUND", message_for("NOT_FOUND"), status=404),
    413: error_response("BODY_TOO_LARGE", message_for("BODY_TOO_LARGE"), status=413),
    500: error_response("INTERNAL", message_for("INTERNAL"), status=500),
}


# ========== 健康检查支持 (P5-E) ==========


class HealthStatus:
    """健康检查聚合结果"""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


def health_check_payload(checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """
    汇总多个组件的健康检查结果

    checks: {"accounts_db": {"status": "ok", "detail": "..."}, ...}
    任何一个 check.status == "down" → 整体 status = "down" → HTTP 503
    所有 check.status == "ok" → 整体 status = "ok" → HTTP 200
    否则 → "degraded" → HTTP 200(降级但可用)
    """
    statuses = [c.get("status", HealthStatus.OK) for c in checks.values()]
    if any(s == HealthStatus.DOWN for s in statuses):
        overall = HealthStatus.DOWN
    elif all(s == HealthStatus.OK for s in statuses):
        overall = HealthStatus.OK
    else:
        overall = HealthStatus.DEGRADED

    return {
        "status": overall,
        "checks": checks,
    }
