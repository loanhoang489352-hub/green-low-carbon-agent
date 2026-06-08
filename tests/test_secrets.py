"""
验证 P0-1 修复:API 密钥不泄漏

P0-1 之前:.env 含 4 个真实 API 密钥(DEEPSEEK/HEFENG/GAODE/MINIMAX)被提交到 git。
P0-1 之后:.env 改为占位符 __SET_ME__,真实密钥从历史清除。
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
PLACEHOLDER = "__SET_ME__"

# 真实密钥的特征:通常以 sk- 开头(MiniMax/DeepSeek 风格)或为 32+ 字符十六进制
SUSPICIOUS_PATTERNS = [
    re.compile(r"sk-cp-r-[A-Za-z0-9_-]{40,}"),  # MiniMax
    re.compile(r"sk-[a-f0-9]{32,}"),            # DeepSeek / OpenAI
    re.compile(r"[a-f0-9]{32,}"),               # 和风 / 高德(无前缀)
]


def test_env_uses_placeholders():
    """所有 API_KEY 行必须是占位符"""
    content = ENV_PATH.read_text(encoding="utf-8")
    violations = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if "API_KEY" not in key and "GROUP_ID" not in key:
            continue
        if value.strip() and value.strip() != PLACEHOLDER:
            for pat in SUSPICIOUS_PATTERNS:
                if pat.search(value):
                    violations.append(f"{key}={value[:30]}...")
                    break
    assert not violations, f"以下密钥看起来是真实的,应为 {PLACEHOLDER}:\n  " + "\n  ".join(violations)
    print(f"✅ test_env_uses_placeholders PASSED")


def test_env_is_gitignored():
    """.env 不在 git 跟踪中"""
    result = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    tracked = result.stdout.strip()
    assert not tracked, f".env 仍在 git 跟踪中: {tracked!r}"
    print("✅ test_env_is_gitignored PASSED")


def test_env_example_has_placeholders():
    """.env.example 必须是占位符或空"""
    example = REPO_ROOT / ".env.example"
    if not example.exists():
        print("⚠️  test_env_example_has_placeholders SKIPPED (no .env.example)")
        return
    content = example.read_text(encoding="utf-8")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if "KEY" in key and value and value != PLACEHOLDER and len(value) > 20:
            assert False, f".env.example 包含可能的真实密钥: {key}={value[:30]}..."
    print("✅ test_env_example_has_placeholders PASSED")


if __name__ == "__main__":
    test_env_uses_placeholders()
    test_env_is_gitignored()
    test_env_example_has_placeholders()
    print("\n🎉 all secrets tests passed")
