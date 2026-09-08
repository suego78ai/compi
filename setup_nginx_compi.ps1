<#
.SYNOPSIS
    setup_nginx_compi.ps1 - Windows Nginx Auto Proxy Configuration for compi.mojuk.kr
    Target Server: 211.105.65.13
    Proxy Target : http://127.0.0.1:26240
#>
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = "compi.mojuk.kr Nginx Setup"

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   [compi.mojuk.kr] Windows Nginx 프록시 자동 설정 스크립트" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan

# 1. Nginx 실행 파일 및 디렉토리 탐색
$nginxProc = Get-Process nginx -ErrorAction SilentlyContinue | Select-Object -First 1
$nginxPath = ""
$nginxDir = ""

if ($nginxProc -and $nginxProc.Path) {
    $nginxPath = $nginxProc.Path
    $nginxDir = Split-Path -Parent $nginxPath
    Write-Host "[감지] 실행 중인 Nginx 발견: $nginxPath" -ForegroundColor Green
} else {
    # 일반적인 설치 경로 탐색
    $candidates = @(
        "C:\nginx\nginx.exe",
        "D:\nginx\nginx.exe",
        "C:\tools\nginx\nginx.exe",
        "D:\tools\nginx\nginx.exe",
        "$env:ProgramFiles\nginx\nginx.exe"
    )
    foreach ($cand in $candidates) {
        if (Test-Path $cand) {
            $nginxPath = $cand
            $nginxDir = Split-Path -Parent $cand
            Write-Host "[감지] Nginx 설치 경로 발견: $nginxPath" -ForegroundColor Green
            break
        }
    }
}

if (-not $nginxDir) {
    Write-Host "[안내] Nginx 경로를 자동으로 감지하지 못했습니다." -ForegroundColor Yellow
    $inputDir = Read-Host "Nginx가 설치된 디렉토리 경로를 입력하세요 (예: C:\nginx)"
    if ($inputDir -and (Test-Path (Join-Path $inputDir "nginx.exe"))) {
        $nginxDir = $inputDir
        $nginxPath = Join-Path $inputDir "nginx.exe"
    } else {
        Write-Host "[오류] 올바른 Nginx 디렉토리를 찾지 못했습니다." -ForegroundColor Red
        Exit 1
    }
}

$confDir = Join-Path $nginxDir "conf"
$confDDir = Join-Path $confDir "conf.d"

if (-not (Test-Path $confDDir)) {
    New-Item -ItemType Directory -Path $confDDir -Force | Out-Null
}

$targetConfFile = Join-Path $confDDir "compi.mojuk.kr.conf"

# 2. 설정 파일 내용 생성
$confContent = @"
# ==============================================================================
# compi.mojuk.kr Reverse Proxy Configuration
# ==============================================================================
server {
    listen 80;
    server_name compi.mojuk.kr;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:26240;
        proxy_http_version 1.1;

        proxy_set_header Upgrade `$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host `$host;
        proxy_set_header X-Real-IP `$remote_addr;
        proxy_set_header X-Forwarded-For `$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto `$scheme;

        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        send_timeout 300s;
        proxy_buffering off;
    }
}
"@

Set-Content -Path $targetConfFile -Value $confContent -Encoding UTF8
Write-Host "[성공] 프록시 설정 파일 생성 완료: $targetConfFile" -ForegroundColor Green

# 3. nginx.conf 내 conf.d include 확인
$mainNginxConf = Join-Path $confDir "nginx.conf"
if (Test-Path $mainNginxConf) {
    $mainContent = Get-Content $mainNginxConf -Raw
    if ($mainContent -notmatch 'include.*conf\.d/\*\.conf;') {
        Write-Host "[안내] nginx.conf 내 conf.d/*.conf 인클루드 구문 추가 중..." -ForegroundColor Cyan
        # http { 블록 끝에 include 추가
        if ($mainContent -match 'http\s*\{') {
            $updatedContent = $mainContent -replace '(http\s*\{)', "`$1`n    include conf.d/*.conf;"
            Set-Content -Path $mainNginxConf -Value $updatedContent -Encoding UTF8
            Write-Host "[완료] nginx.conf에 include conf.d/*.conf; 추가 완료" -ForegroundColor Green
        }
    }
}

# 4. Nginx 문법 검사
Write-Host "[검증] Nginx 설정 문법 검사 중..." -ForegroundColor Cyan
Push-Location $nginxDir
try {
    $testOutput = & $nginxPath -t 2>&1
    Write-Host ($testOutput -join "`n") -ForegroundColor Gray
    
    if ($LASTEXITCODE -eq 0 -or ($testOutput -match 'syntax is ok')) {
        Write-Host "✔ Nginx 설정 문법 검사 성공!" -ForegroundColor Green
        
        Write-Host "[반영] Nginx 설정 재로드(Reload) 중..." -ForegroundColor Cyan
        & $nginxPath -s reload 2>&1 | Out-Null
        Write-Host "🎉 Nginx 재로드 성공! 이제 http://compi.mojuk.kr 로 바로 접속하실 수 있습니다." -ForegroundColor Green
    } else {
        Write-Host "❌ Nginx 설정 문법 검사에 문제가 있습니다. 출력 내용을 확인해 주세요." -ForegroundColor Red
    }
} finally {
    Pop-Location
}

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "설정 완료. 아무 키나 누르면 창이 닫힙니다." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
