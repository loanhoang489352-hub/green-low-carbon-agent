#!/usr/bin/env bash
# P6.S.13: Git Bash / WSL / Linux 用户的启动脚本
# 功能同 agent.bat,但用 bash 语法
# 用法: bash agent.sh [cli|doctor|help]
set -e

cd "$(dirname "$0")"

# LLM_MOCK 完全由 Python 端 dotenv + llm.get_llm_client() 处理
# 这里只设 huggingface 离线
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

case "${1:-web}" in
    web)
        echo "[INFO] Web server mode (default, port 8000)"
        echo "[HINT] bash agent.sh cli       CLI mode"
        echo "[HINT] bash agent.sh doctor    Run diagnostics"
        echo "[HINT] bash agent.sh help      Show all options"
        echo "[NOTE] LLM_MOCK from .env (override: export LLM_MOCK=true)"
        echo
        python -X utf8 src/main.py
        ;;
    cli)
        echo "[INFO] CLI mode"
        python -X utf8 src/main.py --cli
        ;;
    doctor)
        echo "[INFO] Running diagnostics"
        python -X utf8 scripts/doctor.py "${@:2}"
        ;;
    help|-h|--help)
        echo "Usage: agent.sh [mode]"
        echo
        echo "Modes:"
        echo "  (none)   Web server (default, port 8000)"
        echo "  cli      Interactive CLI"
        echo "  doctor   Run diagnostics"
        echo "  help     Show this message"
        ;;
    *)
        echo "Unknown mode: $1"
        echo "Run 'bash agent.sh help' for usage"
        exit 1
        ;;
esac
