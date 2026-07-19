@echo off
chcp 65001 >nul
title 绿色低碳智能体 - 停止

echo.
echo 正在停止绿色低碳智能体服务...

REM 杀端口 8000
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM 杀 cloudflared
taskkill /F /IM cloudflared.exe >nul 2>&1

REM 杀 python main.py
taskkill /F /IM python.exe /FI "WINDOWTITLE eq GreenAgent-Server*" >nul 2>&1

echo.
echo 已停止。
echo.
pause
