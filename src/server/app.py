"""
应用工厂
将 RequestHandler 改造为通过 RouterRegistry 分发
"""
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs

from .router import Route, get_registry
from .routers import register_all_routes

# 确保 src 在路径中
script_path = Path(__file__).resolve()
SRC_DIR = script_path.parent.parent
PROJECT_ROOT = SRC_DIR.parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


MAX_BODY_SIZE = 2_000_000
DEFAULT_CORS_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8000"


class RoutedRequestHandler(BaseHTTPRequestHandler):
    """通过 RouterRegistry 分发的请求处理器"""

    project_root = PROJECT_ROOT

    def _cors_origin(self) -> str:
        allowed = os.environ.get("CORS_ORIGINS", DEFAULT_CORS_ORIGINS)
        origins = [o.strip() for o in allowed.split(",") if o.strip()]
        if not origins:
            return "http://127.0.0.1:8000"
        return ",".join(origins)

    def send_json(self, data, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode("utf-8"))

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _read_body(self) -> str:
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > MAX_BODY_SIZE:
            self.send_error(413, f"Body too large (max {MAX_BODY_SIZE})")
            return ""
        if content_length < 0:
            self.send_error(400, "Invalid Content-Length")
            return ""
        return self.rfile.read(content_length).decode("utf-8") if content_length else ""

    def _dispatch(self, method: str):
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body() if method == "POST" else ""
        data = {}
        if body:
            try:
                data = json.loads(body)
            except Exception as e:
                self.send_error(400, f"Invalid JSON: {e}")
                return

        registry = get_registry()
        route = registry.find(method, path)
        if route is None:
            self.send_error(404, f"Not Found: {method} {path}")
            return

        try:
            if method == "GET":
                route.handler(self)
            else:
                route.handler(self, data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.send_error(500, f"Internal error: {e}")

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def log_message(self, format, *args):
        print(f"[HTTP] {args[0]}")


def create_handler():
    """工厂:返回带全局代理的 RequestHandler 子类"""
    class HandlerWithGlobals(RoutedRequestHandler):
        @property
        def agent(self):
            from main import get_agent
            return get_agent()

        @property
        def policy_updater(self):
            from main import get_policy_updater
            return get_policy_updater()

        @property
        def feedback_manager(self):
            from main import get_feedback_manager
            return get_feedback_manager()

        @property
        def account_manager(self):
            from main import get_account_manager
            return get_account_manager()

    return HandlerWithGlobals


def init_app():
    """初始化应用:注册所有路由"""
    registry = get_registry()
    register_all_routes(registry)
    return create_handler()
