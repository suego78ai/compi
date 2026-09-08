@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion

echo ================================================================
echo   [compi.mojuk.kr] Nginx 리버스 프록시 원클릭 자동 설정기
echo   대상 서버: 211.105.65.13 ^| 프록시 대상: http://127.0.0.1:26240
echo ================================================================
echo.

:: 관리자 권한 확인 및 상승
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [안내] 관리자 권한으로 스크립트를 재실행합니다...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0setup_nginx_compi.ps1"

pause
