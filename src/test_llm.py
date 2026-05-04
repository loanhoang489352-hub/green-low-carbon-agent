"""
Test LLM configuration
"""
import sys
import os
from pathlib import Path

# Setup UTF-8 BEFORE any other imports
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent
sys.path.insert(0, str(project_root / 'src'))

# Load .env
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

results = []
results.append("=" * 60)
results.append("LLM Configuration Check")
results.append("=" * 60)

results.append(f"API_PROVIDER: {os.environ.get('API_PROVIDER', 'not set')}")
results.append(f"DEEPSEEK_API_KEY: {'SET' if os.environ.get('DEEPSEEK_API_KEY') else 'NOT SET'}")

try:
    from llm.client import create_llm_client

    provider = os.environ.get("API_PROVIDER", "openai")
    api_key = os.environ.get("DEEPSEEK_API_KEY")

    client = create_llm_client(provider=provider, api_key=api_key)
    results.append(f"Client type: {type(client).__name__}")
    results.append(f"Client available: {client.is_available()}")

    if client.is_available():
        messages = [{"role": "user", "content": "What is carbon neutral?"}]
        response = client.chat(messages)
        results.append(f"Response: {response[:200]}...")
    else:
        results.append("Client not available")

except Exception as e:
    results.append(f"Error: {e}")

# Write to file
output_file = project_root / "llm_test_result.txt"
with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(results))

print("Check llm_test_result.txt for results")
