@echo off
REM P6.S.2 fix: chcp 65001 MUST be the first line before any non-ASCII content
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM P6.S.13: 让 .env 决定 LLM_MOCK(用户的 .env 已配 DEEPSEEK_API_KEY 真 key)
REM   - 默认:从 .env 读取 LLM_MOCK(.env 里 LLM_MOCK=false → 走真 LLM)
REM   - 强制 mock:把下面 set LLM_MOCK=true 取消注释
REM   - HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE 保留(避免 CN IP 拉 huggingface.co 慢)
if defined LLM_MOCK goto :skip_mock
REM 仅在 .env 没设 LLM_MOCK 时,默认走 mock(向后兼容,无 key 也能跑)
if not exist .env (
    set LLM_MOCK=true
) else (
    REM 检查 .env 里 LLM_MOCK 行
    findstr /B /C:"LLM_MOCK" .env >nul
    if errorlevel 1 set LLM_MOCK=true
)
:skip_mock
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1

if "%1"=="cli" goto :cli
if "%1"=="doctor" goto :doctor
if "%1"=="help" goto :help
if "%1"=="-h" goto :help
if "%1"=="--help" goto :help
goto :web

:web
echo [INFO] Web server mode (default, port 8000)
echo [HINT] agent.bat cli       CLI mode
echo [HINT] agent.bat doctor    Run diagnostics
echo [HINT] agent.bat help      Show all options
echo [NOTE] LLM_MOCK default from .env (override: set in shell or edit this file)
echo.
python -X utf8 src\main.py
echo.
echo [EXIT] python process ended (check logs above if unexpected)
pause
goto :eof

:cli
echo [INFO] CLI mode
python -X utf8 src\main.py --cli
echo [EXIT] CLI ended
pause
goto :eof

:doctor
echo [INFO] Running diagnostics
python -X utf8 scripts\doctor.py %2 %3
echo [EXIT] Doctor ended
pause
goto :eof

:help
echo Usage: agent.bat [mode]
echo.
echo Modes:
echo   (none)   Web server (default, port 8000)
echo   cli      Interactive CLI
echo   doctor   Run diagnostics
echo   help     Show this message
pause
