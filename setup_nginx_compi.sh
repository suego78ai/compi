#!/usr/bin/env bash
# ==============================================================================
# compi.mojuk.kr Nginx Reverse Proxy Auto Setup Script for Linux
# Target Server: 211.105.65.13 (mojuk.kr Server)
# Proxy Target : http://127.0.0.1:26240
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}   [compi.mojuk.kr] Nginx Reverse Proxy Auto-Configuration Tool ${NC}"
echo -e "${CYAN}================================================================${NC}"

# 1. Root permission check
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}[오류] 루트(관리자) 권한이 필요합니다. sudo 명령어로 실행해 주세요.${NC}"
  echo -e "예시: sudo bash $0"
  exit 1
fi

# 2. Check if Nginx is installed
if ! command -v nginx >/dev/null 2>&1; then
  echo -e "${RED}[오류] Nginx가 설치되어 있지 않습니다.${NC}"
  exit 1
fi

echo -e "${GREEN}✔ Nginx 감지 완료: $(nginx -v 2>&1)${NC}"

# 3. Detect Nginx configuration directory
NGINX_CONF_DIR=""
USE_SITES_AVAILABLE=false

if [ -d "/etc/nginx/conf.d" ]; then
  NGINX_CONF_DIR="/etc/nginx/conf.d"
elif [ -d "/etc/nginx/sites-available" ]; then
  NGINX_CONF_DIR="/etc/nginx/sites-available"
  USE_SITES_AVAILABLE=true
else
  echo -e "${RED}[오류] Nginx 설정 디렉토리(/etc/nginx/conf.d 또는 sites-available)를 찾을 수 없습니다.${NC}"
  exit 1
fi

TARGET_FILE="$NGINX_CONF_DIR/compi.mojuk.kr.conf"
echo -e "${CYAN}[정보] Nginx 설정 파일 생성 경로: $TARGET_FILE${NC}"

# 4. Check for SSL certificates (*.mojuk.kr or mojuk.kr)
SSL_CERT=""
SSL_KEY=""

POSSIBLE_CERTS=(
  "/etc/letsencrypt/live/mojuk.kr/fullchain.pem"
  "/etc/letsencrypt/live/compi.mojuk.kr/fullchain.pem"
  "/etc/ssl/certs/mojuk.kr.crt"
  "/etc/ssl/certs/fullchain.pem"
)

POSSIBLE_KEYS=(
  "/etc/letsencrypt/live/mojuk.kr/privkey.pem"
  "/etc/letsencrypt/live/compi.mojuk.kr/privkey.pem"
  "/etc/ssl/private/mojuk.kr.key"
  "/etc/ssl/private/privkey.pem"
)

for i in "${!POSSIBLE_CERTS[@]}"; do
  if [ -f "${POSSIBLE_CERTS[$i]}" ] && [ -f "${POSSIBLE_KEYS[$i]}" ]; then
    SSL_CERT="${POSSIBLE_CERTS[$i]}"
    SSL_KEY="${POSSIBLE_KEYS[$i]}"
    echo -e "${GREEN}✔ 기존 mojuk.kr SSL 인증서 감지: $SSL_CERT${NC}"
    break
  fi
done

# 5. Generate Configuration
cat << 'EOF' > "$TARGET_FILE"
# ==============================================================================
# compi.mojuk.kr Reverse Proxy Configuration
# ==============================================================================
server {
    listen 80;
    listen [::]:80;
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
EOF

# If SSL certificate exists, append HTTPS server block
if [ -n "$SSL_CERT" ] && [ -n "$SSL_KEY" ]; then
  cat << EOF >> "$TARGET_FILE"

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name compi.mojuk.kr;

    ssl_certificate $SSL_CERT;
    ssl_certificate_key $SSL_KEY;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:26240;
        proxy_http_version 1.1;

        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;

        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
        send_timeout 300s;
        proxy_buffering off;
    }
}
EOF
fi

# 6. Enable site if using sites-available
if [ "$USE_SITES_AVAILABLE" = true ]; then
  mkdir -p /etc/nginx/sites-enabled
  ln -sf "$TARGET_FILE" /etc/nginx/sites-enabled/compi.mojuk.kr.conf
  echo -e "${GREEN}✔ sites-enabled 심볼릭 링크 생성 완료${NC}"
fi

# 7. Test Nginx Configuration
echo -e "${CYAN}[검증] Nginx 설정 문법 테스트 중...${NC}"
if nginx -t; then
  echo -e "${GREEN}✔ Nginx 설정 문법 테스트 통과!${NC}"
else
  echo -e "${RED}[오류] Nginx 설정 문법 테스트에 실패했습니다. 이전 상태를 확인해 주세요.${NC}"
  exit 1
fi

# 8. Reload Nginx
echo -e "${CYAN}[반영] Nginx 데몬 재로드(Reload) 중...${NC}"
if systemctl is-active --quiet nginx 2>/dev/null; then
  systemctl reload nginx
elif command -v nginx >/dev/null 2>&1; then
  nginx -s reload
fi

echo -e "${GREEN}================================================================${NC}"
echo -e "${GREEN}🎉 compi.mojuk.kr Nginx 프록시 설정이 성공적으로 완료되었습니다!${NC}"
echo -e "${GREEN}================================================================${NC}"
echo -e "👉 서비스 접속 주소: http://compi.mojuk.kr"
if [ -n "$SSL_CERT" ]; then
  echo -e "👉 보안 접속 주소: https://compi.mojuk.kr"
else
  echo -e "${YELLOW}※ SSL 미적용 상태입니다. Let's Encrypt를 사용하시려면 아래 명령어를 실행하세요:${NC}"
  echo -e "   sudo certbot --nginx -d compi.mojuk.kr"
fi
echo -e "※ 백엔드 포트(26240)가 로컬에서 가동 중인지 확인하세요."
