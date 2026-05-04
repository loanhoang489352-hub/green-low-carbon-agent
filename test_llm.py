"""Test LLM configuration"""
import sys
import os
from pathlib import Path

script_path = Path(__file__).resolve()
src_path = script_path.parent / "src"

if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

results = []
output_file = script_path.parent / "llm_test_result.txt"

try:
    env_file = script_path.parent / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key.strip()] = value.strip()

    results.append("API_PROVIDER: " + str(os.environ.get('API_PROVIDER', 'not set')))
    results.append("DEEPSEEK_API_KEY: " + ("SET" if os.environ.get('DEEPSEEK_API_KEY') else "NOT SET"))

    from llm.client import create_llm_client

    provider = os.environ.get("API_PROVIDER", "openai")
    api_key = os.environ.get("DEEPSEEK_API_KEY")

    results.append("Creating client: " + provider)
    client = create_llm_client(provider=provider, api_key=api_key)
    results.append("Client type: " + type(client).__name__)
    results.append("Client available: " + str(client.is_available()))

    if client.is_available():
        messages = [{"role": "user", "content": "What is carbon neutral?"}]
        response = client.chat(messages)
        results.append("Response: " + response[:200])
    else:
        results.append("Client not available - check API key or network")

except Exception as e:
    import traceback
    results.append("Error: " + str(e))
    results.append(traceback.format_exc())

with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(results))
