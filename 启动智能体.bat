@echo off
chcp 65001 >nul
title 绿色低碳智能体

echo ================================================
echo 绿色低碳智能体
echo ================================================
echo.

cd /d "%~dp0src"

REM 使用 Python Launcher 选择 3.12 版本（如果有）
py -3.12 main.py --cli 2>nul || python main.py --cli

pause
