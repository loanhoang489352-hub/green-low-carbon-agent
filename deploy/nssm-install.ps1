# ========== 绿色低碳智能体 - Windows 服务安装脚本 (P5-J) ==========
# 工具: NSSM (Non-Sucking Service Manager) https://nssm.cc
# 用法(管理员 PowerShell):
#   cd deploy
#   .\nssm-install.ps1
# 卸载:
#   nssm stop GreenAgent
#   nssm remove GreenAgent confirm

#Requires -RunAsAdministrator

$ErrorActionPreference = "Stop"

# ========== 配置 ==========
$ServiceName = "GreenAgent"
$ServiceDisplayName = "绿色低碳智能体 (Green Low-Carbon Agent v2.0)"
$ServiceDescription = "基于消费者偏好建模的个性化低碳生活助手,使用 Python + LangGraph + RAG"
$AppRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = (Get-Command python).Source
$MainScript = Join-Path $AppRoot "src\main.py"
$LogDir = Join-Path $AppRoot "data\logs"
$StdoutLog = Join-Path $LogDir "service-stdout.log"
$StderrLog = Join-Path $LogDir "service-stderr.log"

# 写日志目录
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# ========== 查 NSSM ==========
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $nssm) {
    Write-Error @"
[NSSM 未找到] 请先下载 NSSM 并加入 PATH:
  1. 访问 https://nssm.cc/download
  2. 解压 nssm-2.24.zip
  3. 把 nssm-2.24\win64\nssm.exe 复制到 C:\Windows\System32\
  4. 重新运行本脚本
"@
    exit 1
}

Write-Host "[1/5] 检查服务是否已存在..."
$existing = nssm status $ServiceName 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  [WARN] 服务 '$ServiceName' 已存在,先停止并移除"
    nssm stop $ServiceName 2>&1 | Out-Null
    Start-Sleep -Seconds 2
    nssm remove $ServiceName confirm 2>&1 | Out-Null
}

Write-Host "[2/5] 安装服务..."
nssm install $ServiceName $PythonPath $MainScript
if ($LASTEXITCODE -ne 0) { throw "nssm install 失败" }

Write-Host "[3/5] 配置服务参数..."
nssm set $ServiceName AppDirectory $AppRoot
nssm set $ServiceName DisplayName $ServiceDisplayName
nssm set $ServiceName Description $ServiceDescription
nssm set $ServiceName Start SERVICE_AUTO_START
nssm set $ServiceName AppEnvironmentExtra "PYTHONPATH=$AppRoot\src" "PYTHONUNBUFFERED=1" "ENV=production" "LOG_FILE=$LogDir\app.log"
nssm set $ServiceName AppStdout $StdoutLog
nssm set $ServiceName AppStderr $StderrLog
nssm set $ServiceName AppStdoutCreationDisposition 4   # OPEN_ALWAYS
nssm set $ServiceName AppStderrCreationDisposition 4
nssm set $ServiceName AppRotateFiles 1                  # 启用轮转
nssm set $ServiceName AppRotateBytes 104857600         # 100MB
nssm set $ServiceName AppRotateSeconds 0                # 仅按大小
# P5-J: 优雅停止(SIGTERM → Python 端 waiting inflight ≤10s)
nssm set $ServiceName AppStopMethodSkip 0
nssm set $ServiceName AppStopMethodConsole 0
nssm set $ServiceName AppStopMethodWindow 0
nssm set $ServiceName AppStopMethodThreads 0
# 进程退出时的强杀阈值(毫秒)
nssm set $ServiceName AppKillProcessTree 1
nssm set $ServiceName WaitFlags 0                       # 0 = 等所有进程退出

# 失败时自动重启
nssm set $ServiceName AppExit default Restart
nssm set $ServiceName AppRestartDelay 5000             # 5s

Write-Host "[4/5] 配置日志轮转(注册表 AppRotation)..."
# NSSM 日志轮转通过注册表 HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\$ServiceName\Parameters
# 已在 AppRotateFiles/AppRotateBytes 设置

Write-Host "[5/5] 启动服务..."
nssm start $ServiceName
if ($LASTEXITCODE -ne 0) { throw "nssm start 失败" }

Start-Sleep -Seconds 3
$status = nssm status $ServiceName
Write-Host ""
Write-Host "═══ 安装完成 ═══"
Write-Host "  服务名: $ServiceName"
Write-Host "  状态:   $status"
Write-Host "  路径:   $AppRoot"
Write-Host ""
Write-Host "常用命令:"
Write-Host "  启动:   nssm start $ServiceName"
Write-Host "  停止:   nssm stop $ServiceName  (走 SIGTERM,等待 inflight ≤10s)"
Write-Host "  重启:   nssm restart $ServiceName"
Write-Host "  状态:   nssm status $ServiceName"
Write-Host "  卸载:   nssm remove $ServiceName confirm"
Write-Host ""
Write-Host "日志:"
Write-Host "  stdout: $StdoutLog"
Write-Host "  stderr: $StderrLog"
Write-Host "  应用:   $LogDir\app.log  (JSON 格式,P5-B)"
Write-Host ""
Write-Host "健康探活:"
Write-Host "  curl http://localhost:8000/api/health"
