@echo off
cd /d "%~dp0"

set CLOUDFLARED=scripts\cloudflared\cloudflared.exe

if not exist "%CLOUDFLARED%" (
    echo [ERROR] cloudflared.exe not found at %CLOUDFLARED%
    echo Please download cloudflared.exe to scripts\cloudflared\ first.
    pause
    exit /b 1
)

echo ==============================================
echo   Green Agent - Public Tunnel (Cloudflare)
echo ==============================================
echo.
echo   Prereq: app running on http://localhost:8000
echo   Mode: quick tunnel (no account, random URL)
echo.
echo   A URL like https://xxxx.trycloudflare.com will show below.
echo   Share that URL with your test users.
echo.
echo   Stop: close this window or press Ctrl+C
echo.

"%CLOUDFLARED%" tunnel --url http://localhost:8000

echo.
echo [Tunnel closed] Press any key to exit.
pause >nul
