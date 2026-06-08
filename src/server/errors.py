"""
统一错误响应(P2.1 占位)
"""
from typing import Any, Dict


def error_response(code: str, message: str, status: int = 400, **extra: Any) -> Dict[str, Any]:
    """构造标准错误响应"""
    payload = {"error": {"code": code, "message": message, "status": status}}
    payload["error"].update(extra)
    return payload


COMMON_ERRORS = {
    400: error_response("BAD_REQUEST", "Invalid request"),
    401: error_response("UNAUTHORIZED", "Authentication required", status=401),
    403: error_response("FORBIDDEN", "Permission denied", status=403),
    404: error_response("NOT_FOUND", "Resource not found", status=404),
    413: error_response("BODY_TOO_LARGE", "Request body too large", status=413),
    500: error_response("INTERNAL_ERROR", "Internal server error", status=500),
}
