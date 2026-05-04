# -*- coding: utf-8 -*-
"""Test GreenAgent"""
import sys
import os
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

from pathlib import Path

# Setup paths
script_dir = Path(__file__).resolve().parent
src_dir = script_dir / "src"
project_root = script_dir

# Add src to path
sys.path.insert(0, str(src_dir))
os.chdir(str(src_dir))

# Load .env
env_file = project_root / ".env"
if env_file.exists():
    for line in open(env_file, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

try:
    from agent.core import GreenAgent

    agent = GreenAgent(
        knowledge_base_path=str(project_root / "knowledge_base"),
        enable_rag=True,
        use_llm=True
    )

    result = agent.chat_enhanced(
        user_id="test",
        message="What is carbon neutral?",
        conversation_id="test"
    )

    print("=" * 50)
    print("TEST RESULT")
    print("=" * 50)
    print(f"Intent: {result.intent}")
    print(f"Message: {result.message[:300]}")
    print("=" * 50)
    print("SUCCESS!")

except Exception as e:
    import traceback
    print("=" * 50)
    print("TEST FAILED")
    print("=" * 50)
    print(str(e))
    traceback.print_exc()
