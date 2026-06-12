@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM P6.S.2 fix: 默认走 LLM_MOCK + HF_HUB_OFFLINE,避免 .env key 失效时 401
REM                 + 大陆 IP 拉 huggingface.co 慢。设真 key 后把这两行注释即可
set LLM_MOCK=true
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

if "%1"=="cli" (
    echo [INFO] CLI mode
    python -X utf8 src\main.py --cli
    goto :eof
)
if "%1"=="doctor" (
    echo [INFO] Diagnostics
    python -X utf8 scripts\doctor.py %2 %3
    goto :eof
)
if "%1"=="help" goto :help
if "%1"=="-h" goto :help
if "%1"=="--help" goto :help

echo [INFO] Web server (default mode, port 8000)
echo [HINT] agent.bat cli       CLI mode
echo [HINT] agent.bat doctor    Run diagnostics
echo [HINT] agent.bat help      Show all options
echo [NOTE] LLM_MOCK=true (想用真 LLM 改 agent.bat 头部那 3 行)
echo.
python -X utf8 src\main.py
goto :eof

:help
echo Usage: agent.bat [mode]
echo.
echo Modes:
echo   (none)   Web server (default, port 8000)
echo   cli      Interactive CLI
echo   doctor   Run diagnostics
echo   help     Show this message
