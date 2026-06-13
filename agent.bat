@echo off
REM P6.S.2 fix: chcp 65001 MUST be the first line before any non-ASCII content
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM P6.S.2: default to LLM_MOCK + HF_HUB_OFFLINE
REM   - avoids 401 when .env keys are placeholders
REM   - avoids slow huggingface.co download from CN IP
REM   - comment out these 3 lines to use real LLM keys
set LLM_MOCK=true
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
echo [NOTE] LLM_MOCK=true (set real keys: edit top of this file)
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
