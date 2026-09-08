#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
setup_nginx_compi.py - Cross-platform Nginx Proxy Setup for compi.mojuk.kr
Supports Linux (/etc/nginx) and Windows (C:/nginx, etc.)
Target Server: 211.105.65.13
Proxy Target: http://127.0.0.1:26240
"""
import os
import sys
import platform
import subprocess
from pathlib import Path

CONFIG_TEMPLATE = """# ==============================================================================
# compi.mojuk.kr Reverse Proxy Configuration
# ==============================================================================
server {
    listen 80;
    server_name compi.mojuk.kr;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:26240;
        proxy_http_version 1.1;

        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        send_timeout 300s;
        proxy_buffering off;
    }
}
"""

def setup_linux():
    print("[1/4] Linux Nginx 환경 감지 중...")
    if os.geteuid() != 0:
        print("❌ [오류] 루트 권한이 필요합니다. 'sudo python3 setup_nginx_compi.py'로 실행해 주세요.")
        sys.exit(1)

    conf_dir = None
    use_sites = False
    if os.path.isdir("/etc/nginx/conf.d"):
        conf_dir = Path("/etc/nginx/conf.d")
    elif os.path.isdir("/etc/nginx/sites-available"):
        conf_dir = Path("/etc/nginx/sites-available")
        use_sites = True
    else:
        print("❌ [오류] Nginx 설정 디렉토리를 찾을 수 없습니다.")
        sys.exit(1)

    target_file = conf_dir / "compi.mojuk.kr.conf"
    print(f"[2/4] 설정 파일 생성: {target_file}")
    target_file.write_text(CONFIG_TEMPLATE, encoding="utf-8")

    if use_sites:
        enabled_file = Path("/etc/nginx/sites-enabled/compi.mojuk.kr.conf")
        enabled_file.parent.mkdir(parents=True, exist_ok=True)
        if enabled_file.exists() or enabled_file.is_symlink():
            enabled_file.unlink()
        enabled_file.symlink_to(target_file)
        print("✔ sites-enabled 심볼릭 링크 연결 완료")

    print("[3/4] Nginx 설정 문법 검사 (nginx -t)...")
    res = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    print(res.stderr or res.stdout)
    if res.returncode != 0:
        print("❌ [오류] Nginx 문법 검사 실패")
        sys.exit(1)

    print("[4/4] Nginx 설정 재로드 (systemctl reload nginx)...")
    subprocess.run(["systemctl", "reload", "nginx"])
    print("================================================================")
    print("🎉 compi.mojuk.kr 프록시 설정이 완료되었습니다! (http://compi.mojuk.kr)")
    print("================================================================")

def setup_windows():
    print("[1/4] Windows Nginx 환경 감지 중...")
    candidates = [
        Path("C:/nginx"),
        Path("D:/nginx"),
        Path("C:/tools/nginx"),
        Path("D:/tools/nginx")
    ]
    nginx_dir = None
    for cand in candidates:
        if (cand / "nginx.exe").exists():
            nginx_dir = cand
            break

    if not nginx_dir:
        input_path = input("Nginx 설치 디렉토리를 입력하세요 (예: C:\\nginx): ").strip()
        if input_path and (Path(input_path) / "nginx.exe").exists():
            nginx_dir = Path(input_path)
        else:
            print("❌ [오류] nginx.exe를 찾을 수 없습니다.")
            sys.exit(1)

    conf_d = nginx_dir / "conf" / "conf.d"
    conf_d.mkdir(parents=True, exist_ok=True)
    target_file = conf_d / "compi.mojuk.kr.conf"

    print(f"[2/4] 설정 파일 생성: {target_file}")
    target_file.write_text(CONFIG_TEMPLATE, encoding="utf-8")

    # Check include in nginx.conf
    main_conf = nginx_dir / "conf" / "nginx.conf"
    if main_conf.exists():
        content = main_conf.read_text(encoding="utf-8", errors="ignore")
        if "conf.d/*.conf" not in content:
            print("✔ nginx.conf 에 'include conf.d/*.conf;' 구문 추가")
            new_content = content.replace("http {", "http {\n    include conf.d/*.conf;")
            main_conf.write_text(new_content, encoding="utf-8")

    nginx_exe = nginx_dir / "nginx.exe"
    print("[3/4] Nginx 설정 문법 검사 (nginx.exe -t)...")
    res = subprocess.run([str(nginx_exe), "-t"], cwd=str(nginx_dir), capture_output=True, text=True)
    print(res.stderr or res.stdout)
    if res.returncode != 0:
        print("❌ [오류] Nginx 문법 검사 실패")
        sys.exit(1)

    print("[4/4] Nginx 재로드 (nginx.exe -s reload)...")
    subprocess.run([str(nginx_exe), "-s", "reload"], cwd=str(nginx_dir))
    print("================================================================")
    print("🎉 compi.mojuk.kr 프록시 설정이 완료되었습니다! (http://compi.mojuk.kr)")
    print("================================================================")

def main():
    os_name = platform.system().lower()
    if "linux" in os_name:
        setup_linux()
    elif "windows" in os_name:
        setup_windows()
    else:
        print(f"지원하지 않는 운영체제입니다: {os_name}")

if __name__ == "__main__":
    main()
