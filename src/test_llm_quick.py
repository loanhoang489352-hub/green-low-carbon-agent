"""Quick LLM test - file output"""
import sys
import os
from pathlib import Path

script_path = Path(__file__).resolve()
project_root = script_path.parent.parent

# Load env first
env_file = project_root / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()

results = []
results.append("=" * 50)
results.append("LLM DIAGNOSTIC TEST")
results.append("=" * 50)
results.append(f"PROJECT_ROOT: {project_root}")
results.append(f"ENV FILE: {env_file}")
results.append(f"ENV EXISTS: {env_file.exists()}")
results.append("")
results.append(f"API_PROVIDER: {os.environ.get('API_PROVIDER', 'NOT SET')}")
results.append(f"DEEPSEEK_API_KEY: {'SET' if os.environ.get('DEEPSEEK_API_KEY') else 'NOT SET'}")

sys.path.insert(0, str(script_path.parent))

try:
    from llm.client import create_llm_client
    client = create_llm_client(
        provider=os.environ.get("API_PROVIDER", "deepseek"),
        api_key=os.environ.get("DEEPSEEK_API_KEY")
    )
    results.append("")
    results.append(f"CLIENT TYPE: {type(client).__name__}")
    results.append(f"CLIENT AVAILABLE: {client.is_available()}")

    if client.is_available():
        messages = [{"role": "user", "content": "Say 'OK'"}]
        response = client.chat(messages)
        results.append(f"LLM RESPONSE: {response[:200]}")
    else:
        results.append("ERROR: Client not available - check API key!")

except Exception as e:
    import traceback
    results.append(f"ERROR: {e}")
    results.append(traceback.format_exc())

# Write to file
output_file = project_root / "diagnostic_result.txt"
with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(results))
