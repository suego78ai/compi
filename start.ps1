# ==============================================================================
# compi_start - Server Startup Script (Supports compi.mojuk.kr & localhost)
# ==============================================================================
$host.UI.RawUI.WindowTitle = "compi_start"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $scriptDir

# 1. 이전 서버 프로세스 정리 (26240번 포트 및 기존 compi_start 프로세스)
$conns = Get-NetTCPConnection -LocalPort 26240 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Milliseconds 400
}

Get-CimInstance Win32_Process -Filter "CommandLine LIKE '%compi_start%'" -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.ProcessId -ne $PID) {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

# 2. pythonw / python 실행 파일 탐색
$pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue

$execPath = if ($pythonwCmd) { $pythonwCmd.Source } elseif ($pythonCmd) { $pythonCmd.Source } else { "python.exe" }

# 3. 백그라운드 프로세스로 완전 분리(Detached WMI Process) 실행 (창 없이 백그라운드 상시 구동 유지)
$cmdLine = "`"$execPath`" `"$scriptDir\compi_start.py`""
$wmiProcess = [wmiclass]"Win32_Process"
$res = $wmiProcess.Create($cmdLine, $scriptDir, $null)

# 4. 서버 정상 기동 확인 (포트 오픈 대기)
$portOpen = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 250
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient("127.0.0.1", 26240)
        if ($tcp.Connected) {
            $tcp.Close()
            $portOpen = $true
            break
        }
    } catch {}
}

if ($portOpen) {
    Write-Host "[성공] compi 서버가 정상 기동되었습니다 (http://127.0.0.1:26240/)"
} else {
    Write-Host "[경고] 서버 기동 대기 시간 초과"
}

Exit 0
