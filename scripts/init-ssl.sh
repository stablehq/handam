#!/bin/bash
# SSL 초기 인증서 발급 스크립트
# 사용법: DOMAIN=your-domain.com EMAIL=admin@your-domain.com bash scripts/init-ssl.sh

set -e

DOMAIN="${DOMAIN:?DOMAIN 환경변수를 설정해주세요 (예: DOMAIN=handam.example.com)}"
EMAIL="${EMAIL:?EMAIL 환경변수를 설정해주세요 (예: EMAIL=admin@example.com)}"

echo "=== SSL 인증서 발급 시작 ==="
echo "도메인: $DOMAIN"
echo "이메일: $EMAIL"

# 1. certbot 디렉토리 생성
mkdir -p certbot/conf certbot/www

# 2. nginx를 HTTP 전용으로 시작 (기본 nginx.conf가 HTTP 서빙)
echo ">>> 백엔드 + nginx 시작..."
docker compose -f docker-compose.prod.yml up -d backend frontend

# 3. 백엔드 헬스체크 대기
echo ">>> 백엔드 시작 대기..."
for i in $(seq 1 30); do
  if docker compose -f docker-compose.prod.yml exec backend curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "백엔드 시작 완료"
    break
  fi
  echo "대기 중... ($i/30)"
  sleep 2
done

# 4. certbot으로 인증서 발급
echo ">>> certbot 인증서 발급 중..."
docker compose -f docker-compose.prod.yml run --rm certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    -d "$DOMAIN" \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email

# 5. nginx SSL 설정으로 교체
echo ">>> nginx SSL 설정 적용 중..."
docker compose -f docker-compose.prod.yml exec frontend sh -c \
    "sed 's/your-domain.com/$DOMAIN/g' /etc/nginx/conf.d/nginx-ssl.conf.template > /etc/nginx/conf.d/default.conf"

# 6. nginx 재시작 (SSL 적용)
docker compose -f docker-compose.prod.yml exec frontend nginx -s reload

echo "=== SSL 인증서 발급 완료 ==="
echo "https://$DOMAIN 으로 접속해보세요."
