# 작업 스케줄러에 세 작업을 등록한다: evas-memo-app, evas-memo-caddy, evas-memo-duckdns
#   기본: 컴퓨터가 켜질 때 로그인 없이 실행 (Windows 비밀번호를 한 번 묻는다. 파일에 저장하지 않는다)
#   -Logon: 비밀번호 없이, 이 계정으로 로그인할 때 실행
#   -System: 비밀번호 없이, SYSTEM 계정으로 컴퓨터가 켜질 때 실행(Windows 계정에 비밀번호가 없을 때 쓴다)
# 관리자 권한 필요. install-tasks.bat을 우클릭 > 관리자 권한으로 실행.
param([switch]$Logon, [switch]$System)
$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { throw "관리자 권한이 필요합니다. install-tasks.bat을 우클릭해서 '관리자 권한으로 실행'하세요." }

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not (Test-Path "$root\.env")) { throw ".env가 없습니다: $root" }

# 작업은 PATH 없이도 돌도록 파이썬 실제 경로를 지금 찾아 박아 둔다
$py = (& python -c "import sys;print(sys.executable)").Trim()
# 5.1에서는 Stop 상태로 stderr를 받으면 파이썬 오류가 그대로 예외가 되어 아래 안내 문구에 못 닿는다
$ErrorActionPreference = "Continue"
& $py -c "import uvicorn, fastapi, itsdangerous, dotenv, httpx, pycrdt" 2>$null
$pkgOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = "Stop"
if (-not $pkgOk) { throw "패키지가 없습니다. 먼저 실행: $py -m pip install -r requirements.txt" }
if (-not (Get-Command caddy -ErrorAction SilentlyContinue)) { throw "caddy.exe를 PATH에서 찾지 못했습니다 (C:\caddy 를 PATH에 추가했는지 확인)" }

$user = "$env:USERDOMAIN\$env:USERNAME"

if ($System) {
    # SYSTEM은 사용자 폴더의 OneDrive 파일(온라인 전용 표시 파일)을 내려받지 못하고, 사용자 PATH도 못 본다
    if ($root -match "OneDrive") { throw "OneDrive 폴더 안입니다. C:\evas-memo 처럼 동기화 안 되는 곳으로 옮긴 뒤 다시 실행하세요." }
    $caddyDir = (Split-Path (Get-Command caddy).Source).TrimEnd("\")
    $machinePath = ([Environment]::GetEnvironmentVariable("Path", "Machine") -split ";") | ForEach-Object { $_.TrimEnd("\") }
    if ($machinePath -notcontains $caddyDir) { throw "caddy 폴더($caddyDir)가 '시스템 변수' Path에 없습니다(사용자 변수에만 있으면 SYSTEM이 못 찾습니다)." }
}
# 앱은 꺼지면 안 되므로: 실행 시간 제한 없음(기본 72시간 뒤 중지 방지), 죽으면 1분 뒤 최대 3회 재시작
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

if ($System) {
    $boot = New-ScheduledTaskTrigger -AtStartup
    $who = @{ Principal = (New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest) }
} elseif ($Logon) {
    $boot = New-ScheduledTaskTrigger -AtLogOn -User $user
    $who = @{ Principal = (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Highest) }
} else {
    $boot = New-ScheduledTaskTrigger -AtStartup
    $pw = Read-Host "Windows 로그인 비밀번호 ($user)" -AsSecureString
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pw))
    $who = @{ User = $user; Password = $plain; RunLevel = "Highest" }
}

function Add-Task($name, $action, $triggers) {
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings @who -Force | Out-Null
    Write-Host "등록 완료: $name"
}

Add-Task "evas-memo-app" (New-ScheduledTaskAction -Execute $py -Argument "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" -WorkingDirectory $root) $boot
Add-Task "evas-memo-caddy" (New-ScheduledTaskAction -Execute "$root\scripts\run-caddy.bat" -WorkingDirectory $root) $boot

# DuckDNS는 .env에 token이 있을 때만(공유기 DDNS 등 다른 주소를 쓰면 필요 없다)
if (Select-String -Path "$root\.env" -Pattern '^DUCKDNS_TOKEN=.+' -Quiet) {
    $every5 = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
    Add-Task "evas-memo-duckdns" (New-ScheduledTaskAction -Execute $py -Argument "scripts\duckdns_update.py" -WorkingDirectory $root) @($boot, $every5)
} else {
    Write-Host "건너뜀: evas-memo-duckdns (.env에 DUCKDNS_TOKEN 없음)"
}
$plain = $null

Write-Host ""
Write-Host "끝. 지금 열려 있는 run-app.bat / run-caddy.bat 창을 닫은 뒤 아래로 시작하거나 PC를 재부팅하세요."
Write-Host "  schtasks /Run /TN evas-memo-app"
Write-Host "  schtasks /Run /TN evas-memo-caddy"
