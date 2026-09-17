"""
HTML 报告路由:P14
- GET /api/reports/by-user/<uid>/<YYYY>/<MM>/<filename> — 服务指定 HTML 报告
- GET /api/reports/list — 列出当前用户的报告(供前端"我的报告"页面用)
- 安全:路径遍历防护(限定在 data/reports/ 子目录),身份认证
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import unquote

from paths import REPORTS_DIR

_log = logging.getLogger(__name__)

# 报告根目录(统一走 paths.DATA_DIR,避免 parents[2] 算浅一层导致写读分裂到 src/data)
_REPORTS_ROOT = REPORTS_DIR


def _safe_resolve(rel_path: str) -> Path:
    """路径遍历防护:解析相对路径,确保在 _REPORTS_ROOT 下"""
    if not rel_path:
        raise ValueError("空路径")
    # 拒绝 .. / 绝对路径 / 危险符号
    rel_path = unquote(rel_path)
    if ".." in rel_path.split("/") or rel_path.startswith("/") or rel_path.startswith("\\"):
        raise ValueError(f"非法路径: {rel_path}")
    full = (_REPORTS_ROOT / rel_path).resolve()
    if not str(full).startswith(str(_REPORTS_ROOT.resolve())):
        raise ValueError(f"路径逃逸: {rel_path}")
    return full


def register_report_routes(registry) -> None:
    """注册报告相关路由"""

    def serve_report(handler, *args):
        """
        GET /api/reports/by-user/<uid>/YYYY/MM/<filename>
        GET /api/reports/by-date/YYYY-MM-DD/<filename>
        服务 HTML 报告文件(text/html),浏览器直接打开
        """
        from server.errors import APIError

        # URL 模式: /api/reports/<rest...>
        # 从 handler.path 切出 reports/ 之后的子路径
        path = getattr(handler, "path", "")
        prefix = "/api/reports/"
        if not path.startswith(prefix):
            raise APIError("NOT_FOUND", f"未知报告路径: {path}")

        rel = path[len(prefix):]
        try:
            full = _safe_resolve(rel)
        except ValueError as e:
            raise APIError("BAD_REQUEST", str(e))

        if not full.exists() or not full.is_file():
            raise APIError("NOT_FOUND", f"报告不存在: {rel}")

        # 鉴权:报告含个人画像,需要登录用户与报告 user_id 一致(或 admin)
        try:
            current = getattr(handler, "current_user", None) or {}
            user_id = current.get("user_id")
        except Exception:
            user_id = None

        if user_id:
            # 报告路径里应包含 user_id(by-user/<uid>/...)— 校验一致
            if "/by-user/" in rel and f"/{user_id}/" not in rel:
                raise APIError("FORBIDDEN", "无权访问他人报告")
            # by-date/ 不带 user_id 也能看(匿名 demo)
        # 未登录用户:放行(适合匿名 demo 路径)

        # 读文件 + 返回
        try:
            content = full.read_text(encoding="utf-8")
        except Exception as e:
            raise APIError("INTERNAL", f"读报告失败: {e}")

        handler.send_response_only(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(content.encode("utf-8"))))
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        handler.wfile.write(content.encode("utf-8"))

    def list_reports(handler):
        """
        GET /api/reports/list
        列出当前用户的所有 HTML 报告(按日期倒序)
        """
        from server.errors import APIError

        current = getattr(handler, "current_user", None) or {}
        user_id = current.get("user_id")

        if not user_id:
            # 未登录返回空列表
            handler.send_json({"ok": True, "reports": []})
            return

        user_dir = _REPORTS_ROOT / "by-user" / user_id
        if not user_dir.exists():
            handler.send_json({"ok": True, "reports": []})
            return

        reports = []
        for path in sorted(user_dir.rglob("*.html"), reverse=True):
            if not path.is_file():
                continue
            try:
                rel = path.relative_to(_REPORTS_ROOT)
                url = f"/api/reports/{rel.as_posix()}"
                stat = path.stat()
                reports.append({
                    "url": url,
                    "filename": path.name,
                    "path": str(path),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                    "user_id": user_id,
                })
            except Exception as e:
                _log.warning("[reports] 列出 %s 失败: %s", path, e)
                continue

        handler.send_json({"ok": True, "reports": reports[:50], "count": len(reports)})

    # 注册路由(前缀匹配 — Router 支持 `^` 前缀)
    # 报告文件本身用「capability URL」保护:文件名含随机 secret(见 core.py 生成逻辑),
    # 拿到 URL 才能看,故 serve_report 保持 auth_required=False(浏览器可直接点开)。
    # list_reports 泄露报告清单,必须鉴权。
    registry.add_route(
        "GET", "^/api/reports/by-user/", serve_report, auth_required=False,
    )
    registry.add_route(
        "GET", "^/api/reports/by-date/", serve_report, auth_required=False,
    )
    registry.add_route(
        "GET", "/api/reports/list", list_reports, auth_required=True,
    )


__all__ = ["register_report_routes", "serve_report", "list_reports"]