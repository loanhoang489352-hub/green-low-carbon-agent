#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Full chat test"""
import sys
import os
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent

# Load env FIRST
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

# Redirect stdout to file BEFORE any imports
original_stdout = sys.stdout
original_stderr = sys.stderr
log_file = open(project_root / "chat_test_result.txt", "w", encoding="utf-8")
sys.stdout = log_file
sys.stderr = log_file

results = []
results.append("=" * 50)
results.append("FULL CHAT TEST")
results.append("=" * 50)

sys.path.insert(0, str(script_path.parent))

try:
    from agent.core import GreenAgent

    results.append("\n[1] Initializing GreenAgent...")
    agent = GreenAgent(
        knowledge_base_path=str(project_root / "knowledge_base"),
        enable_rag=True,
        use_llm=True
    )
    results.append(f"    use_llm: {agent.use_llm}")
    results.append(f"    rag_enabled: {agent.rag_enabled}")

    results.append("\n[2] Testing chat...")
    result = agent.chat_enhanced(
        user_id="test_user",
        message="What is carbon neutral?",
        conversation_id="test_conv"
    )

    results.append(f"\n[3] Result:")
    results.append(f"    intent: {result.intent}")
    results.append(f"    message: {result.message[:300]}...")
    results.append(f"    suggestions: {result.suggestions}")
    results.append("\n[SUCCESS] Test completed!")

except Exception as e:
    import traceback
    results.append(f"\n[ERROR] {e}")
    results.append(traceback.format_exc())

# Write to file
log_file.write("\n".join(results))
log_file.close()
sys.stdout = original_stdout
sys.stderr = original_stderr
print("Results written to chat_test_result.txt")
