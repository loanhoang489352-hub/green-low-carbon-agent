"""
结构化日志 (P5-B)

特性:
- JSONFormatter: 每条日志输出单行 JSON,自动注入 trace_id / timestamp / level / logger
- setup_logging(): 启动时配置 root logger(同时 stdout + 文件)
- get_logger(__name__): 拿模块 logger,调用 logger.info("event", extra={...})

设计:
- 默认日志级别 INFO,从 settings 读 LOG_LEVEL
- 默认日志文件 data/logs/app.log,自动 mkdir
- 不抛异常:文件创建失败时退化到纯 stdout
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from observability.trace import get_trace_id


class JSONFormatter(logging.Formatter):
    """JSON 单行格式化器,自动注入 trace_id"""

    DEFAULT_FIELDS = {
        "name", "msg", "args", "levelname", "levelno",
        "pathname", "filename", "module", "exc_info",
        "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread",
        "threadName", "processName", "process", "message",
        "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "trace_id": get_trace_id(),
        }

        # 用户传入的 extra 字段
        for k, v in record.__dict__.items():
            if k not in self.DEFAULT_FIELDS and not k.startswith("_"):
                try:
                    json.dumps(v)
                    payload[k] = v
                except (TypeError, ValueError):
                    payload[k] = str(v)

        # 异常信息
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    also_stdout: bool = True,
) -> None:
    """
    配置全局日志

    Args:
        level: 日志级别 ("DEBUG"/"INFO"/"WARNING"/"ERROR")
        log_file: 日志文件路径(None = 不写文件)
        also_stdout: 是否同时输出到 stdout
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有 handler(避免重复)
    for h in list(root.handlers):
        root.removeHandler(h)

    formatter = JSONFormatter()

    if also_stdout:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        root.addHandler(sh)

    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            root.addHandler(fh)
        except Exception as e:
            # 文件创建失败不阻塞,只 warn 到 stderr
            print(f"[WARN] 无法创建日志文件 {log_file}: {e}", file=sys.stderr)


def get_logger(name: str) -> logging.Logger:
    """拿 logger(直接传 __name__)"""
    return logging.getLogger(name)


__all__ = ["JSONFormatter", "setup_logging", "get_logger"]
