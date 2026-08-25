Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  입시 웹사이트 서버를 시작합니다." -ForegroundColor Green
Write-Host "  주소: http://127.0.0.1:26240" -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 기존 26240번 포트 프로세스가 실행 중이면 정리
$conns = Get-NetTCPConnection -LocalPort 26240 -ErrorAction SilentlyContinue
if ($conns) {
    Write-Host "[안내] 이전 서버 프로세스(26240번 포트)를 종료합니다..." -ForegroundColor Yellow
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

# 2. 서버가 가동되어 포트가 열리면 웹 브라우저 자동 오픈
$job = Start-Job -ScriptBlock {
    $portOpen = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Milliseconds 500
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
        Start-Process "http://127.0.0.1:26240"
    }
}

# 3. 파이썬 웹 서버 실행
try {
    python main.py
} catch {
    Write-Host "[오류] 서버 실행 중 오류가 발생했습니다: $_" -ForegroundColor Red
} finally {
    Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
}

