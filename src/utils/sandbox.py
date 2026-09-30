"""
子进程沙箱(P17)

隔离执行 —— 用于 MCP stdio 服务(以及未来"执行代码"类工具):
- 环境净化: 子进程默认不继承完整父环境(不透传 LLM key / DB 凭据),只透传白名单
- 资源限制: 内存/CPU/文件描述符(POSIX 用 resource.setrlimit;Windows 降级为超时)
- 超时强杀 + 输出截断(防撑爆内存)

跨平台:
  - POSIX: preexec_fn 设 RLIMIT_AS / RLIMIT_CPU / RLIMIT_NOFILE
  - Windows: 无 resource 模块,仅超时兜底(资源限制需 Job Object,留作增强)

安全边界说明: 这是"进程级隔离 + 资源限制",不是 Docker 级隔离。若需内核级
隔离(不可信代码),应用 docker/nsjail;本模块覆盖"可信但可能出错"的工具/MCP 服务。
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# 子进程默认继承的最小环境变量(不含任何密钥)
_BASE_ENV_KEYS = (
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE",
    "TMPDIR", "TEMP", "TMP",
    "PYTHONPATH", "PYTHONUNBUFFERED", "PYTHONIOENCODING", "PYTHONUTF8",
    "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT",
    "SSL_CERT_FILE", "CURL_CA_BUNDLE",
)

# 默认资源限制(POSIX)
_DEFAULT_MAX_MEMORY_BYTES = 1024 * 1024 * 1024  # 1GB
_DEFAULT_MAX_CPU_SECONDS = 60
_DEFAULT_MAX_OPEN_FILES = 256
_DEFAULT_MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # 1MB


@dataclass
class SandboxResult:
    """一次性执行结果"""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def sandbox_env(extra_keys: Optional[List[str]] = None) -> Dict[str, str]:
    """构造净化后的子进程环境:仅透传基础安全键 + 白名单键。

    Args:
        extra_keys: 需要额外透传的环境变量名(如 GAODE_API_KEY),缺省不传密钥。
    """
    env: Dict[str, str] = {}
    for k in _BASE_ENV_KEYS:
        if k in os.environ:
            env[k] = os.environ[k]
    for k in (extra_keys or []):
        if k in os.environ:
            env[k] = os.environ[k]
    return env


def _posix_preexec():
    """子进程内(POSIX)设置资源限制。任何失败都忽略(不阻塞主路径)。"""
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (_DEFAULT_MAX_MEMORY_BYTES, _DEFAULT_MAX_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (_DEFAULT_MAX_CPU_SECONDS, _DEFAULT_MAX_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_NOFILE, (_DEFAULT_MAX_OPEN_FILES, _DEFAULT_MAX_OPEN_FILES))
    except Exception:
        pass


def sandbox_popen_kwargs(
    env_extra_keys: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
) -> Dict:
    """返回传给 subprocess.Popen 的沙箱 kwargs(env + 资源限制)。

    用于长驻子进程(MCP stdio server)的启动隔离。
    env 显式传入时优先(调用方已拼好白名单);否则用 sandbox_env(env_extra_keys)。
    """
    kwargs: Dict = {"env": env if env is not None else sandbox_env(env_extra_keys)}
    if cwd:
        kwargs["cwd"] = cwd
    # POSIX: 用 preexec_fn 设资源限制;Windows: 跳过(无 resource 模块)
    if os.name == "posix":
        kwargs["preexec_fn"] = _posix_preexec
    return kwargs


def run_sandboxed(
    command: str,
    args: Optional[List[str]] = None,
    timeout: float = 10.0,
    cwd: Optional[str] = None,
    env_extra_keys: Optional[List[str]] = None,
    max_output_bytes: int = _DEFAULT_MAX_OUTPUT_BYTES,
) -> SandboxResult:
    """一次性沙箱执行(未来"执行代码"类工具用)。

    超时强杀 + 输出截断 + 环境净化 + 资源限制。
    """
    cmd = [command] + list(args or [])
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **sandbox_popen_kwargs(env_extra_keys, cwd),
        )
        try:
            out, err = proc.communicate(timeout=timeout)
            return SandboxResult(
                stdout=out.decode("utf-8", "replace")[:max_output_bytes],
                stderr=err.decode("utf-8", "replace")[:max_output_bytes],
                exit_code=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            _kill(proc)
            return SandboxResult(
                stderr=f"执行超时(>{timeout}s),已终止",
                exit_code=-1,
                timed_out=True,
            )
    except FileNotFoundError:
        return SandboxResult(stderr=f"命令不存在: {command}", exit_code=127)
    except Exception as e:
        return SandboxResult(stderr=f"沙箱执行失败: {e}", exit_code=126)


def _kill(proc: subprocess.Popen) -> None:
    """超时强杀(先 SIGTERM,1s 后 SIGKILL)"""
    try:
        proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=1)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


__all__ = ["SandboxResult", "sandbox_env", "sandbox_popen_kwargs", "run_sandboxed"]
