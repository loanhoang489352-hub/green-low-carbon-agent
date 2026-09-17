#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自测 LLM 是否真的调用(而非 mock)。
用法: 项目根目录执行  python scripts\\check_llm.py
会把 model / error / content 三行打印;把这三行贴给 AI 即可判断。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 关键:像 main.py 一样先加载项目根 .env(否则 DEEPSEEK_API_KEY / LLM_MOCK=false 不在环境里,
# DeepSeek 拿不到 key → 退化为 mock,从而误判)
env_file = ROOT / ".env"
if env_file.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except ImportError:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from llm import get_llm_client  # noqa: E402


def main() -> int:
    client = get_llm_client()
    resp = client.chat([{"role": "user", "content": "你好"}])
    print("provider =", os.environ.get("API_PROVIDER", "?"))
    print("model    =", resp.model)
    print("error    =", resp.error)
    print("content  =", (resp.content or "")[:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
