"""Test LLM with debug logging"""
import sys
import os
from pathlib import Path

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
print("Test LLM Integration")
print("=" * 60)
print(f"API_PROVIDER: {os.environ.get('API_PROVIDER')}")
print(f"DEEPSEEK_API_KEY: {'SET' if os.environ.get('DEEPSEEK_API_KEY') else 'NOT SET'}")

# Test LLM client directly
from llm.client import create_llm_client
provider = os.environ.get("API_PROVIDER", "openai")
api_key = os.environ.get("DEEPSEEK_API_KEY")
client = create_llm_client(provider=provider, api_key=api_key)
print(f"Client created: {type(client).__name__}")
print(f"Available: {client.is_available()}")

# Test ResponseGenerator
from agent.response import ResponseGenerator, ResponseContext

rg = ResponseGenerator(use_llm=True)
print(f"ResponseGenerator._use_llm: {rg._use_llm}")

# Create a test context
context = ResponseContext(
    user_profile={},
    conversation_history=[],
    retrieved_knowledge=[],
    recent_memories=[],
    intent_type="knowledge_query"
)

# Try to generate with LLM
try:
    print("Calling generate_with_llm...")
    result = rg.generate_with_llm(
        user_input="What is carbon neutral?",
        context=context,
        rag_context=""
    )
    print(f"Success! Response: {result[:100]}...")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
