# Green Agent - API verification script (ASCII-only to avoid PS5.1 encoding issues)
# Run with server up on localhost:8000, from a separate terminal:
#   cd D:\green-agent
#   Set-ExecutionPolicy -Scope Process Bypass
#   .\scripts\verify_api.ps1

$ErrorActionPreference = "Stop"
$Base = "http://localhost:8000/api"
$u = "testuser" + (Get-Random -Minimum 100000 -Maximum 999999)

Write-Host "== 0. register + login ==" -ForegroundColor Cyan
try { Invoke-RestMethod -Method Post -Uri "$Base/auth/register" -ContentType "application/json" -Body (@{username=$u; password="testpass123"} | ConvertTo-Json) | Out-Null } catch { Write-Host "   (user may already exist, ignore)" -ForegroundColor DarkGray }
$login = Invoke-RestMethod -Method Post -Uri "$Base/auth/login" -ContentType "application/json" -Body (@{username=$u; password="testpass123"} | ConvertTo-Json)
$sid = $login.session_id
$uid = $login.user_id
Write-Host ("   user_id      = " + $uid) -ForegroundColor Green
Write-Host ("   session_id   = " + $sid.Substring(0,[Math]::Min(12,$sid.Length)) + "...") -ForegroundColor Green
$headers = @{ Authorization = "Bearer $sid" }

Write-Host "== 1. chat/enhanced (check recommendations not empty) ==" -ForegroundColor Cyan
# Build the Chinese knowledge-query message via Unicode code points so the
# .ps1 stays ASCII (avoids PS5.1 UTF-8/GBK mojibake) while sending correct text:
#   "北京有哪些低碳生活政策?"
$chatMsg = [string]::Join('', @([char]0x5317,[char]0x4EAC,[char]0x6709,[char]0x54EA,[char]0x4E9B,[char]0x4F4E,[char]0x78B3,[char]0x751F,[char]0x6D3B,[char]0x653F,[char]0x7B56,[char]0xFF1F))
$chat = Invoke-RestMethod -Method Post -Uri "$Base/chat/enhanced" -Headers $headers -ContentType "application/json" -Body (@{message=$chatMsg} | ConvertTo-Json)
Write-Host ("   intent            = " + $chat.intent) -ForegroundColor Green
Write-Host ("   recommendations   = " + @($chat.recommendations).Count + " items") -ForegroundColor Green

Write-Host "== 2. energy profile (write) ==" -ForegroundColor Cyan
$appliances = @("air_conditioner","water_heater","fridge","washer","dishwasher")
$profileBody = @{user_id=$uid; family_size=3; home_size_sqm=80; city="beijing"; appliances=$appliances; monthly_electricity_bill=220; monthly_water_bill=60; monthly_gas_bill=80}
$p1 = Invoke-RestMethod -Method Post -Uri "$Base/energy/profile" -Headers $headers -ContentType "application/json" -Body ($profileBody | ConvertTo-Json -Depth 6)
Write-Host ("   ok = " + $p1.ok + "  persisted = " + $p1.persisted + "  level = " + $p1.delegation_level) -ForegroundColor Green

Write-Host "== 3. energy profile (read, new GET endpoint) ==" -ForegroundColor Cyan
$p2 = Invoke-RestMethod -Method Get -Uri "$Base/energy/profile" -Headers $headers
Write-Host ("   ok = " + $p2.ok + "  profile city = " + $p2.profile.city + "  appliances = " + @($p2.profile.appliances).Count) -ForegroundColor Green

Write-Host "== 4. energy plan (category>=2 and source_ref present) ==" -ForegroundColor Cyan
$plan = Invoke-RestMethod -Method Post -Uri "$Base/energy/plan" -Headers $headers -ContentType "application/json" -Body (@{user_id=$uid} | ConvertTo-Json)
if ($plan.ok -ne $true) {
  Write-Host ("   blocked = " + $plan.blocked + "  warning = " + $plan.warning) -ForegroundColor Yellow
} else {
  $actions = @($plan.plan.actions)
  $cats = @($actions | ForEach-Object { $_.category } | Sort-Object -Unique)
  $noSrc = @($actions | Where-Object { -not $_.source_ref }).Count
  Write-Host ("   actions = " + $actions.Count + "  categories = " + ($cats -join ",") + "  missing_source_ref = " + $noSrc) -ForegroundColor Green
  $first = $actions[0]
  Write-Host ("   sample: " + $first.title + " | $" + $first.estimated_saving_cny + " | " + $first.source_ref) -ForegroundColor DarkGray
}

Write-Host "== 5. today card / pending / stats ==" -ForegroundColor Cyan
$today = Invoke-RestMethod -Method Get -Uri "$Base/energy/today" -Headers $headers
Write-Host ("   today.goal = " + $today.today_card.goal) -ForegroundColor Green
$pending = Invoke-RestMethod -Method Get -Uri "$Base/energy/actions?status=pending" -Headers $headers
Write-Host ("   pending = " + $pending.count + " items") -ForegroundColor Green
$stats = Invoke-RestMethod -Method Get -Uri "$Base/energy/stats?period=week" -Headers $headers
Write-Host ("   stats: cny=" + $stats.total_saving_cny + "  co2=" + $stats.total_saving_co2_kg + "  streak=" + $stats.streak_days) -ForegroundColor Green

Write-Host "== PASS/FAIL summary ==" -ForegroundColor Cyan
Write-Host ("   02 recommendations not empty? " + (@($chat.recommendations).Count -ge 1)) -ForegroundColor Green
Write-Host "   If any error above, paste the whole output to me." -ForegroundColor DarkGray
