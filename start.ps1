# ==============================================================================
# compi_start - Safe Server Startup Script (Supports compi.mojuk.kr & localhost)
# Strictly isolates compi server processes and prevents terminating any other program
# ==============================================================================
$host.UI.RawUI.WindowTitle = "compi_start"

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
if (-not $scriptDir) { $scriptDir = (Get-Item .).FullName }
Set-Location $scriptDir

$pidFile = Join-Path $scriptDir "compi_server.pid"

function Test-IsCompiServerProcess {
    param([object]$proc)
    if (-not $proc) { return $false }
    $cmd = $proc.CommandLine
    if (-not $cmd) { return $false }

    if ($cmd -match 'compi_start\.py') {
        $normalizedScriptDir = $scriptDir.Replace('/', '\').TrimEnd('\')
        $normalizedCmd = $cmd.Replace('/', '\')
        if ($normalizedCmd.IndexOf($normalizedScriptDir, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or $normalizedCmd.IndexOf('ipsi', [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }
    return $false
}

function Stop-SpecificProcessSafe {
    param(
        [int]$ProcessId,
        [string]$Reason
    )
    if (-not $ProcessId -or $ProcessId -eq $PID) { return }

    $proc = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $proc) { return }

    if (Test-IsCompiServerProcess -proc $proc) {
        Write-Host "[정리] 기존 compi 서버(PID: $ProcessId, $Reason)를 안전하게 종료합니다..."
        Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 6; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { break }
        }
        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "[보호] PID $ProcessId ($($proc.Name)) 프로세스는 compi 서버가 아니므로 보호합니다."
    }
}

# 1. 26240번 포트 사전 점검: 다른 프로그램이 점유 중인지 검사
$conns = Get-NetTCPConnection -LocalPort 26240 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        $ownerPid = $c.OwningProcess
        if ($ownerPid -and $ownerPid -ne 0) {
            $ownerProc = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerPid" -ErrorAction SilentlyContinue
            if ($ownerProc) {
                if (Test-IsCompiServerProcess -proc $ownerProc) {
                    # 기존에 실행되던 우리 compi 인스턴스인 경우 안전하게 종료 후 재기동
                    Stop-SpecificProcessSafe -ProcessId $ownerPid -Reason "26240번 포트 점유"
                } else {
                    # 다른 프로그램인 경우 절대 강제 종료하지 않고 경고 후 안전하게 종료
                    Write-Host "[오류] 26240번 포트가 다른 프로그램($($ownerProc.Name), PID: $ownerPid)에서 이미 사용 중입니다."
                    Write-Host "[보호] 다른 프로그램에 영향을 주지 않기 위해 compi 서버 시작을 중단합니다."
                    Exit 1
                }
            }
        }
    }
    Start-Sleep -Milliseconds 300
}

# 2. 이전에 남겨진 이 디렉터리의 compi_server.pid 또는 compi_start.py 프로세스 정리
if (Test-Path $pidFile) {
    try {
        $savedPidStr = (Get-Content $pidFile -ErrorAction SilentlyContinue | Out-String).Trim()
        if ($savedPidStr -match '^\d+$') {
            Stop-SpecificProcessSafe -ProcessId ([int]$savedPidStr) -Reason "PID 파일 기준"
        }
    } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.ProcessId -ne $PID -and (Test-IsCompiServerProcess -proc $_)) {
        Stop-SpecificProcessSafe -ProcessId $_.ProcessId -Reason "compi_start.py 일치"
    }
}

# 3. pythonw / python 실행 파일 탐색
$pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
$execPath = if ($pythonwCmd) { $pythonwCmd.Source } elseif ($pythonCmd) { $pythonCmd.Source } else { "python.exe" }

# 4. 백그라운드 프로세스로 완전 분리(Detached WMI Process) 실행 (창 없이 백그라운드 상시 구동 유지)
$cmdLine = "`"$execPath`" `"$scriptDir\compi_start.py`""
$wmiProcess = [wmiclass]"Win32_Process"
$res = $wmiProcess.Create($cmdLine, $scriptDir, $null)

if ($res.ReturnValue -eq 0 -and $res.ProcessId) {
    Set-Content -Path $pidFile -Value $res.ProcessId -Encoding utf8
}

# 5. 서버 정상 기동 확인 (포트 오픈 대기)
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
    Write-Host "[경고] 서버 기동 대기 시간 초과 - compi_server.log 로그를 확인해주세요."
}

Exit 0

