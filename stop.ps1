Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  웹 서버(26240번 포트) 종료 중..." -ForegroundColor Yellow
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$conns = Get-NetTCPConnection -LocalPort 26240 -ErrorAction SilentlyContinue
if ($conns) {
    foreach ($c in $conns) {
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[성공] 26240번 포트 프로세스가 종료되었습니다." -ForegroundColor Green
} else {
    Write-Host "[안내] 현재 실행 중인 26240번 포트 서버가 없습니다." -ForegroundColor Gray
}

Start-Sleep -Seconds 2
