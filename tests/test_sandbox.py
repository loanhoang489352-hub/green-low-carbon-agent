"""P17: 子进程沙箱单元测试"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.sandbox import sandbox_env, run_sandboxed, SandboxResult


def test_sandbox_env_leaks_no_secrets(monkeypatch):
    """净化环境只含基础键 + 白名单,不透传 LLM key / DB 凭据"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-owner")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-secret")
    monkeypatch.setenv("GAODE_API_KEY", "amap-key-123")
    env = sandbox_env(extra_keys=["GAODE_API_KEY"])
    assert "GAODE_API_KEY" in env  # 白名单透传
    assert "OPENAI_API_KEY" not in env  # 密钥不透传
    assert "DEEPSEEK_API_KEY" not in env
    assert "PATH" in env  # 基础键保留


def test_run_sandboxed_captures_stdout():
    r = run_sandboxed(sys.executable, ["-c", "print('hello sandbox')"], timeout=10)
    assert r.ok
    assert "hello sandbox" in r.stdout


def test_run_sandboxed_timeout():
    r = run_sandboxed(sys.executable, ["-c", "import time; time.sleep(5)"], timeout=0.5)
    assert r.timed_out is True
    assert r.exit_code != 0


def test_run_sandboxed_command_not_found():
    r = run_sandboxed("definitely-not-a-real-cmd-xyz", timeout=5)
    assert not r.ok
    assert r.exit_code == 127


def test_run_sandboxed_captures_stderr():
    r = run_sandboxed(sys.executable, ["-c", "import sys; sys.stderr.write('err out')"], timeout=10)
    assert "err out" in r.stderr


if __name__ == "__main__":
    test_sandbox_env_leaks_no_secrets(_FakeMonkey())
    test_run_sandboxed_captures_stdout()
    test_run_sandboxed_timeout()
    test_run_sandboxed_command_not_found()
    print("✅ sandbox tests PASSED")


class _FakeMonkey:
    def setenv(self, k, v):
        os.environ[k] = v
