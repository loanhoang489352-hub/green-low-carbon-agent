@echo off
chcp 65001 >nul 2>&1

cd /d "%~dp0"
echo [INFO] Launching server from: %CD%
echo.

python -X utf8 src\main.py