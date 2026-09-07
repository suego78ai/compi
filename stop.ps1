# ==============================================================================
# compi_stop - Server Shutdown Script
# ==============================================================================
$host.UI.RawUI.WindowTitle = "compi_stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# 1. 26240번 포트 점유 프로세스 강제 종료
$conns = Get-NetTCPConnection -LocalPort 26240 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# 2. compi_start 실행 프로세스 정리
Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%compi_start%' OR CommandLine LIKE '%main.py%'" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.ProcessId -ne $PID) {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

Exit 0
