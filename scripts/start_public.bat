@echo off
chcp 65001 >nul
title 绿色低碳智能体 - 公网启动

echo.
echo ========================================
echo   绿色低碳智能体 - 公网部署启动
echo ========================================
echo.

REM 1) 清理旧进程
echo [1/4] 清理端口 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
echo       清理完成
echo.

REM 2) 准备日志目录
if not exist "D:\绿色低碳智能体\logs" mkdir "D:\绿色低碳智能体\logs"

REM 3) 启动 AI 服务
echo [2/4] 启动 AI 服务...
cd /d "D:\绿色低碳智能体\src"
start "GreenAgent-Server" /B cmd /c "python main.py > D:\绿色低碳智能体\logs\agent.log 2>&1"
echo       进程已启动,等待就绪...
echo.

REM 4) 等待 /api/ready
echo [3/4] 等待服务就绪(最多 60 秒)...
set /a COUNT=0
:WAIT_LOOP
set /a COUNT+=1
if %COUNT% gtr 20 goto WAIT_TIMEOUT
timeout /t 3 /nobreak >nul
curl -s --max-time 2 http://localhost:8000/api/ready >nul 2>&1
if %errorlevel% neq 0 goto WAIT_LOOP
echo       服务就绪
echo.
goto START_TUNNEL

:WAIT_TIMEOUT
echo.
echo       [警告] 服务启动超过 60 秒,继续启动隧道
echo       详细日志: D:\绿色低碳智能体\logs\agent.log
echo.

REM 5) 启动公网隧道
:START_TUNNEL
echo [4/4] 启动 Cloudflare 公网隧道...
echo.
echo ========================================
echo   启动中... 等待公网 URL 出现
echo   (首次使用无需 Cloudflare 账号)
echo   (关掉此窗口 = 同时停掉 AI + 隧道)
echo ========================================
echo.

cd /d "D:\绿色低碳智能体"
scripts\cloudflared\cloudflared.exe tunnel --url http://localhost:8000
