"""
统一错误响应 + APIError 异常类 (P5-E)

设计:
- APIError 携带 code + message + status,handler 抛出后 _dispatch 捕获并转 JSON
- 未知异常被 _dispatch 兜底,traceback 写日志,客户端只看到 INTERNAL
- error_response() 构造标准 JSON 响应(向后兼容)
- HTTP_STATUS_MAP 是 code → (status, default_message) 查找表
"""
from typing import Any, Dict, Optional, Tuple


# ========== 错误码 → HTTP 状态映射 ==========

HTTP_STATUS_MAP: Dict[str, Tuple[int, str]] = {
    # 4xx
    "BAD_REQUEST":       (400, "Invalid request"),
    "UNAUTHORIZED":      (401, "Authentication required"),
    "FORBIDDEN":         (403, "Permission denied"),
    "NOT_FOUND":         (404, "Resource not found"),
    "METHOD_NOT_ALLOWED":(405, "Method not allowed"),
    "CONFLICT":          (409, "Resource conflict"),
    "BODY_TOO_LARGE":    (413, "Request body too large"),
    "RATE_LIMITED":      (429, "Too many requests"),
    # 5xx
    "INTERNAL":          (500, "服务暂时不可用"),
    "NOT_IMPLEMENTED":   (501, "Not implemented"),
    "LLM_UNAVAILABLE":   (503, "LLM 暂不可用"),
    "DEPENDENCY_DOWN":   (503, "依赖服务不可用"),
    "TIMEOUT":           (504, "Request timeout"),
}


def status_for(code: str, default: int = 500) -> int:
    """code → HTTP 状态码,未注册则返 default"""
    return HTTP_STATUS_MAP.get(code, (default, ""))[0]


def message_for(code: str) -> str:
    """code → 默认 message,未注册则返 'Unknown error'"""
    return HTTP_STATUS_MAP.get(code, (500, "Unknown error"))[1]


# ========== APIError 异常类 ==========

class APIError(Exception):
    """
    P5-E: 业务异常 — 携带错误码,handler 抛出后由 _dispatch 捕获并转 JSON 响应

    用法:
        if not user_id:
            raise APIError("BAD_REQUEST", "user_id required")
        if not authorized:
            raise APIError("FORBIDDEN", "无权访问此资源")
        if llm_down:
            raise APIError("LLM_UNAVAILABLE", "所有 LLM provider 失败")
    """

    def __init__(self, code: str, message: Optional[str] = None, status: Optional[int] = None, **extra: Any):
        self.code = code
        self.message = message or message_for(code)
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
    400: error_response("BAD_REQUEST", "Invalid request"),
    401: error_response("UNAUTHORIZED", "Authentication required", status=401),
    403: error_response("FORBIDDEN", "Permission denied", status=403),
    404: error_response("NOT_FOUND", "Resource not found", status=404),
    413: error_response("BODY_TOO_LARGE", "Request body too large", status=413),
    500: error_response("INTERNAL", "服务暂时不可用", status=500),
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
