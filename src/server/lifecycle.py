"""
P5-J: 应用生命周期管理 — 启动 + 优雅退出

职责:
    1. 启动阶段:init_app() 调 register_routes / start_scheduler / connect_mcp
    2. 运行阶段:提供 inflight 计数器(已有,移到本模块)
    3. 退出阶段:注册 SIGTERM/SIGINT handler,
       收到信号 → 等待 inflight 排空 → 停止 scheduler → 释放 ChromaDB → WAL checkpoint

设计:
    - 不依赖 main.py 也能被单元测试 import
    - handler 是 idempotent 的,重复调用不会二次副作用
    - SIGTERM 优雅退出 timeout 默认 10s(K8s 默认 terminationGracePeriodSeconds=30,
      docker stop 默认 SIGKILL 在 10s 后,所以 10s 是安全的)

公开 API:
    install_signal_handlers(server, timeout_s=10.0)
    wait_for_inflight_drain(timeout_s)
    get_inflight_count()
    graceful_shutdown(server, timeout_s)
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ========== inflight 计数器(请求级) ==========

_INFLIGHT_COUNT = 0
_INFLIGHT_LOCK = threading.Lock()
_HANDLER_INSTALLED = False
_HANDLER_LOCK = threading.Lock()


def inflight_begin() -> None:
    """请求开始(inflight + 1)"""
    global _INFLIGHT_COUNT
    with _INFLIGHT_LOCK:
        _INFLIGHT_COUNT += 1


def inflight_end() -> None:
    """请求结束(inflight - 1)"""
    global _INFLIGHT_COUNT
    with _INFLIGHT_LOCK:
        _INFLIGHT_COUNT -= 1


def get_inflight_count() -> int:
    """当前在处理的请求数"""
    with _INFLIGHT_LOCK:
        return _INFLIGHT_COUNT


def wait_for_inflight_drain(timeout_s: float = 10.0, poll_interval_s: float = 0.1) -> bool:
    """
    P5-J: 等待 inflight 请求处理完毕(给 SIGTERM 优雅退出用)

    返回: True = 全部完成 / False = 超时仍有未完成
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if get_inflight_count() == 0:
            return True
        time.sleep(poll_interval_s)
    return get_inflight_count() == 0


# ========== 优雅退出 ==========


def graceful_shutdown(server=None, timeout_s: float = 10.0) -> None:
    """
    P5-J: 关闭应用

    步骤:
        1) 等待 inflight 请求处理完毕(≤ timeout_s)
        2) 停止调度器(wait=False,不阻塞)
        3) 释放 ChromaDB PersistentClient 句柄
        4) 强制 SQLite WAL checkpoint(避免丢数据)
        5) 调用 server.shutdown()(若提供)

    参数:
        server:  ThreadingHTTPServer 实例(可选,用于停止 serve_forever 循环)
        timeout_s: 等待 inflight 清零的最大秒数
    """
    # 1) 等待 inflight 排空
    remaining = get_inflight_count()
    if remaining > 0:
        logger.info(
            "[lifecycle] 关闭信号收到,等待 %d 个 inflight 请求完成 (timeout=%.1fs)",
            remaining,
            timeout_s,
        )
        drained = wait_for_inflight_drain(timeout_s=timeout_s)
        remaining_after = get_inflight_count()
        if drained:
            logger.info("[lifecycle] inflight 已全部完成")
        else:
            logger.warning(
                "[lifecycle] 等待超时,仍有 %d 个请求未完成,强制退出",
                remaining_after,
            )

    # 2) 停止调度器
    try:
        from scheduler import stop_scheduler

        stop_scheduler(wait=False)
        logger.info("[lifecycle] 调度器已停止")
    except Exception as e:
        logger.debug("[lifecycle] 调度器停止跳过: %s", e)

    # 3) 释放 ChromaDB PersistentClient 句柄(允许 SQLite WAL checkpoint)
    try:
        from rag.rag_engine import get_rag_engine

        engine = get_rag_engine()
        if engine is not None and getattr(engine, "_vector_store", None) is not None:
            try:
                client = getattr(engine._vector_store, "_client", None)
                if client is not None:
                    engine._vector_store._client = None
                    logger.info("[lifecycle] ChromaDB 客户端句柄已释放")
            except Exception as e:
                logger.debug("[lifecycle] ChromaDB 句柄释放异常: %s", e)
    except Exception as e:
        logger.debug("[lifecycle] RAG 引擎未初始化,跳过 ChromaDB 释放: %s", e)

    # 4) 刷新 SQLite WAL 到主库文件(避免 shutdown 时丢数据)
    try:
        from db.connection import get_all_connections

        conns = get_all_connections()
        for conn in conns:
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except Exception:
                pass
        logger.info("[lifecycle] SQLite WAL checkpoint 完成 (%d conns)", len(conns))
    except Exception as e:
        logger.debug("[lifecycle] SQLite WAL checkpoint 跳过: %s", e)

    # 5) 关闭 server(让 serve_forever 退出)
    if server is not None:
        try:
            server.shutdown()
            logger.info("[lifecycle] HTTP server.shutdown() 已调用")
        except Exception as e:
            logger.debug("[lifecycle] server.shutdown() 异常: %s", e)


# ========== 信号 handler 注册 ==========


def _make_signal_handler(server, timeout_s: float):
    """生成信号 handler(闭包捕获 server / timeout_s)"""

    def _handler(signum, frame):
        try:
            sig_name = signal.Signals(signum).name
        except Exception:
            sig_name = str(signum)
        logger.info(
            "[lifecycle] 收到 %s,开始优雅退出 (wait inflight <=%.1fs)",
            sig_name,
            timeout_s,
        )
        try:
            graceful_shutdown(server=server, timeout_s=timeout_s)
            logger.info(
                "[lifecycle] 优雅退出完成,剩余 inflight=%d",
                get_inflight_count(),
            )
        except Exception as e:
            logger.exception("[lifecycle] 优雅退出异常: %s", e)
        # 兜底:某些情况下 graceful_shutdown 不会触发 server.shutdown()(如没传 server)
        # 此处强制 sys.exit(0) 避免主进程挂起
        import sys

        sys.exit(0)

    return _handler


def install_signal_handlers(server=None, timeout_s: float = 10.0) -> bool:
    """
    注册 SIGTERM / SIGINT handler(Windows 仅 SIGINT / SIGBREAK)

    幂等:重复调用只生效一次。

    参数:
        server:  ThreadingHTTPServer 实例
        timeout_s: 等待 inflight 的最大秒数

    返回: True = 成功注册 / False = 已注册过或不支持(Windows 子进程场景)
    """
    global _HANDLER_INSTALLED
    with _HANDLER_LOCK:
        if _HANDLER_INSTALLED:
            logger.debug("[lifecycle] signal handlers 已注册,跳过")
            return False
        handler = _make_signal_handler(server, timeout_s)

        # Linux/macOS: SIGTERM(K8s / docker stop / systemctl stop)
        registered = []
        if hasattr(signal, "SIGTERM"):
            try:
                signal.signal(signal.SIGTERM, handler)
                registered.append("SIGTERM")
            except (AttributeError, ValueError) as e:
                logger.debug("[lifecycle] SIGTERM 注册失败: %s", e)

        # 全平台: SIGINT(Ctrl+C / docker-compose down)
        try:
            signal.signal(signal.SIGINT, handler)
            registered.append("SIGINT")
        except (AttributeError, ValueError) as e:
            logger.debug("[lifecycle] SIGINT 注册失败: %s", e)

        # Windows: SIGBREAK(Ctrl+Break,Console 控制台关闭事件)
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, handler)
                registered.append("SIGBREAK")
            except (AttributeError, ValueError) as e:
                logger.debug("[lifecycle] SIGBREAK 注册失败: %s", e)

        _HANDLER_INSTALLED = True
        if registered:
            logger.info("[lifecycle] signal handlers 注册成功: %s", registered)
            return True
        logger.warning("[lifecycle] 未注册任何 signal handler")
        return False


def reset_signal_handlers_for_test() -> None:
    """测试用:重置 _HANDLER_INSTALLED 标志(让 test 可多次注册)"""
    global _HANDLER_INSTALLED
    with _HANDLER_LOCK:
        _HANDLER_INSTALLED = False


# ========== 启动阶段封装(可选,简化 main.py) ==========


def init_application() -> object:
    """
    P5-J: 应用启动工厂(可选,简化 main.py)

    步骤:
        1) ensure_data_dirs + init_all_schemas(幂等)
        2) register_all_routes
        3) 注册 tools/skills(P6.S.15)
        4) 启动 MCP registry(P6.S.16)
        5) 注册事件订阅者
        6) 启动 APScheduler

    返回:create_handler()(已注入全局代理)
    """
    from paths import ensure_data_dirs
    from db_schema import init_all_schemas
    from server.router import get_registry
    from server.routers import register_all_routes

    ensure_data_dirs()
    init_all_schemas()

    registry = get_registry()
    register_all_routes(registry)

    # 调用原有 server.app 的注册逻辑(tools/skills/MCP/订阅/调度)
    from server.app import (
        _register_all_tools_and_skills,
        _start_mcp_registry,
        _register_event_subscribers,
        _start_scheduler_safe,
        create_handler,
    )

    _register_all_tools_and_skills()
    _start_mcp_registry()
    _register_event_subscribers()
    _start_scheduler_safe()

    return create_handler()
