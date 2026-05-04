"""Test full chat_enhanced with LLM"""
import sys
import os
from pathlib import Path

# Setup UTF-8 encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Setup paths
script_path = Path(__file__).resolve()
project_root = script_path.parent
src_path = project_root / "src"
sys.path.insert(0, str(src_path))

# Load .env
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

print("=" * 60)
print("Test Full Chat")
print("=" * 60)

# Test GreenAgent
from agent.core import GreenAgent

agent = GreenAgent(
    knowledge_base_path=str(project_root / "knowledge_base"),
    enable_rag=True,
    use_llm=True
)

print(f"\nAgent initialized:")
print(f"  - use_llm: {agent.use_llm}")
print(f"  - rag_enabled: {agent.rag_enabled}")

# Test chat
print("\n[Test] Sending message...")
result = agent.chat_enhanced(
    user_id="test_user",
    message="What is carbon neutral?",
    conversation_id=None
)

print(f"\n[Result]")
print(f"  Intent: {result.intent}")
print(f"  Message: {result.message[:200]}...")
print(f"  Suggestions: {result.suggestions}")
