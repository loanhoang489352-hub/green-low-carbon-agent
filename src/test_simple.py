# -*- coding: utf-8 -*-
"""Test script for GreenAgent"""
import sys
import os
from pathlib import Path

# Suppress ALL warnings before anything else
import warnings
warnings.filterwarnings("ignore")

# Setup paths
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

# Load env
env_file = project_root / ".env"
if env_file.exists():
    for line in open(env_file, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

# Import and test
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

print("SUCCESS")
print(f"Intent: {result.intent}")
print(f"Message: {result.message[:200]}...")
