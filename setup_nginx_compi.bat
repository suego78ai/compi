@echo off
setlocal enabledelayedexpansion
chcp 65001 > nul 2>&1

set "SYSTEM_ROOT=%SystemRoot%"
if "%SYSTEM_ROOT%"=="" set "SYSTEM_ROOT=C:\Windows"
set "PATH=%SYSTEM_ROOT%\System32;%SYSTEM_ROOT%;%SYSTEM_ROOT%\System32\Wbem;%PATH%"

echo ================================================================
echo   [compi.mojuk.kr] Nginx 리버스 프록시 원클릭 자동 설정기
echo   대상 서버: 211.105.65.13 ^| 프록시 대상: http://127.0.0.1:26240
echo ================================================================
echo.

:: 1. 관리자 권한 확인 (net session)
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [안내] 관리자 권한이 필요합니다. 관리자 권한으로 실행해 주세요.
    echo (파일을 우클릭하여 '관리자 권한으로 실행'을 선택하세요.)
    echo.
)

:: 2. Nginx 설치 디렉토리 탐색
set "NGINX_EXE="
set "NGINX_DIR="

:: 2-1. PATH에서 탐색
where nginx.exe >nul 2>&1
if %errorlevel% equ 0 (
    for /f "delims=" %%i in ('where nginx.exe 2^>nul') do (
        if not defined NGINX_EXE (
            set "NGINX_EXE=%%i"
            set "NGINX_DIR=%%~dpi"
        )
    )
)

:: 2-2. 대표적인 기본 경로 탐색
if not defined NGINX_EXE (
    for %%d in (
        "C:\nginx"
        "D:\nginx"
        "C:\tools\nginx"
        "D:\tools\nginx"
        "C:\Program Files\nginx"
        "D:\Program Files\nginx"
    ) do (
        if exist "%%~d\nginx.exe" (
            set "NGINX_EXE=%%~d\nginx.exe"
            set "NGINX_DIR=%%~d\"
        )
    )
)

:: 2-3. 감지 실패 시 사용자 직접 입력
if not defined NGINX_DIR (
    echo [안내] Nginx 설치 경로를 자동으로 감지하지 못했습니다.
    set /p "USER_INPUT_DIR=Nginx 디렉토리 경로를 입력해 주세요 (예: C:\nginx): "
    if exist "!USER_INPUT_DIR!\nginx.exe" (
        set "NGINX_EXE=!USER_INPUT_DIR!\nginx.exe"
        set "NGINX_DIR=!USER_INPUT_DIR!\"
    ) else (
        echo [오류] 해당 경로에서 nginx.exe를 찾을 수 없습니다: !USER_INPUT_DIR!
        echo.
        echo ※ 만약 이 서버가 Linux(Ubuntu/CentOS 등)라면 setup_nginx_compi.sh 를 실행하세요:
        echo   sudo bash setup_nginx_compi.sh
        echo.
        pause
        exit /b 1
    )
)

echo [✔ 감지] Nginx 디렉토리: !NGINX_DIR!

:: 3. conf\conf.d 디렉토리 생성
if not exist "!NGINX_DIR!conf\conf.d" (
    mkdir "!NGINX_DIR!conf\conf.d" 2>nul
)

set "TARGET_CONF=!NGINX_DIR!conf\conf.d\compi.mojuk.kr.conf"
echo [1/3] 설정 파일 생성 중: !TARGET_CONF!

:: 4. 프록시 설정 파일 작성
(
echo # ==============================================================================
echo # compi.mojuk.kr Reverse Proxy Configuration
echo # ==============================================================================
echo server {
echo     listen 80;
echo     server_name compi.mojuk.kr;
echo.
echo     client_max_body_size 50M;
echo.
echo     location / {
echo         proxy_pass http://127.0.0.1:26240;
echo         proxy_http_version 1.1;
echo.
echo         proxy_set_header Upgrade $http_upgrade;
echo         proxy_set_header Connection "upgrade";
echo.
echo         proxy_set_header Host $host;
echo         proxy_set_header X-Real-IP $remote_addr;
echo         proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
echo         proxy_set_header X-Forwarded-Proto $scheme;
echo.
echo         proxy_connect_timeout 300s;
echo         proxy_send_timeout 300s;
echo         proxy_read_timeout 300s;
echo         send_timeout 300s;
echo         proxy_buffering off;
echo     }
echo }
) > "!TARGET_CONF!"

echo [✔ 완료] compi.mojuk.kr.conf 생성 완료!

:: 5. nginx.conf 내 include conf.d 확인
set "MAIN_CONF=!NGINX_DIR!conf\nginx.conf"
if exist "!MAIN_CONF!" (
    findstr /i "conf.d" "!MAIN_CONF!" >nul 2>&1
    if !errorlevel! neq 0 (
        echo [안내] nginx.conf 에 conf.d\*.conf 인클루드 구문 확인 필요
        echo (수동으로 nginx.conf 의 http 블록 내에 'include conf.d/*.conf;' 를 추가해 주시면 더욱 좋습니다.)
    )
)

:: 6. Nginx 문법 검사 및 재로드
echo [2/3] Nginx 설정 문법 검사 (nginx.exe -t)...
pushd "!NGINX_DIR!"
nginx.exe -t
if %errorlevel% neq 0 (
    echo [오류] Nginx 설정 문법에 문제가 있습니다.
    popd
    pause
    exit /b 1
)

echo [3/3] Nginx 설정 재로드 (nginx.exe -s reload)...
nginx.exe -s reload
popd

echo.
echo ================================================================
echo 🎉 compi.mojuk.kr Nginx 프록시 설정 및 재로드가 완료되었습니다!
echo 👉 이제 http://compi.mojuk.kr 로 바로 접속하실 수 있습니다.
echo ================================================================
echo.
pause
