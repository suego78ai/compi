# ==============================================================================
# compi_stop - Safe Server Shutdown Script
# Strictly isolates compi server processes and prevents terminating any other program
# ==============================================================================
$host.UI.RawUI.WindowTitle = "compi_stop"

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
if (-not $scriptDir) { $scriptDir = (Get-Item .).FullName }
Set-Location $scriptDir

$pidFile = Join-Path $scriptDir "compi_server.pid"
$script:stoppedCount = 0

function Test-IsCompiServerProcess {
    param([object]$proc)
    if (-not $proc) { return $false }
    $cmd = $proc.CommandLine
    if (-not $cmd) { return $false }

    # compi_start.py가 명시되어 있는지 확인
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
        Write-Host "[종료] compi 서버(PID: $ProcessId, $Reason)를 종료합니다..."
        Stop-Process -Id $ProcessId -ErrorAction SilentlyContinue
        
        for ($i = 0; $i -lt 6; $i++) {
            Start-Sleep -Milliseconds 250
            if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { break }
        }

        if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
            Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        }
        $script:stoppedCount++
    } else {
        Write-Host "[보호] PID $ProcessId ($($proc.Name)) 프로세스는 compi 서버가 아니므로 종료하지 않고 보호합니다."
    }
}

# 1. compi_server.pid 파일에 기록된 서버 프로세스 확인 및 종료
if (Test-Path $pidFile) {
    try {
        $savedPidStr = (Get-Content $pidFile -ErrorAction SilentlyContinue | Out-String).Trim()
        if ($savedPidStr -match '^\d+$') {
            Stop-SpecificProcessSafe -ProcessId ([int]$savedPidStr) -Reason "PID 파일 기준"
        }
    } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# 2. 혹시 남아있을 수 있는 이 디렉터리의 compi_start.py 프로세스만 정밀 탐색 후 종료 (다른 프로그램은 절대 건드리지 않음)
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.ProcessId -ne $PID -and (Test-IsCompiServerProcess -proc $_)) {
        Stop-SpecificProcessSafe -ProcessId $_.ProcessId -Reason "compi_start.py 일치"
    }
}

# 3. 26240번 포트 점유 프로세스 확인 (오직 compi 서버 프로세스인 경우에만 종료)
$conns = Get-NetTCPConnection -LocalPort 26240 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        if ($c.OwningProcess -and $c.OwningProcess -ne 0) {
            Stop-SpecificProcessSafe -ProcessId $c.OwningProcess -Reason "26240번 포트 점유"
        }
    }
}

if ($script:stoppedCount -gt 0) {
    Write-Host "[성공] compi 서버가 다른 프로그램에 영향 없이 안전하게 종료되었습니다."
} else {
    Write-Host "[알림] 실행 중인 compi 서버가 없거나 이미 종료되었습니다."
}

Exit 0

