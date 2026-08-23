#!/usr/bin/env bash
# reverse-proxy(nginx) 컨테이너용 자체 서명(self-signed) TLS 인증서를
# certs/ 아래에 생성한다.
#
# 어디까지나 임시/개발용이다 — 브라우저가 "신뢰할 수 없는 인증서" 경고를
# 띄운다(사내 PKI가 서명한 게 아니므로). 실제 운영 배포에서는 사내
# 보안팀에서 발급받은 인증서로 certs/server.crt·certs/server.key를
# 교체할 것 — deploy/nginx.conf가 참조하는 파일명은 그대로 두면 된다.
#
# 사용법:
#   scripts/gen_self_signed_cert.sh [도메인]
#   도메인을 생략하면 localhost로 발급한다.

set -euo pipefail

DOMAIN="${1:-localhost}"
CERTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/certs"
CRT_PATH="$CERTS_DIR/server.crt"
KEY_PATH="$CERTS_DIR/server.key"

if ! command -v openssl >/dev/null 2>&1; then
  echo "[gen_self_signed_cert] openssl이 필요합니다." >&2
  exit 1
fi

mkdir -p "$CERTS_DIR"

if [ -f "$CRT_PATH" ] || [ -f "$KEY_PATH" ]; then
  echo "[gen_self_signed_cert] 이미 인증서가 있습니다: $CRT_PATH" >&2
  echo "[gen_self_signed_cert] 새로 만들려면 기존 파일을 먼저 지우세요." >&2
  exit 1
fi

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$KEY_PATH" -out "$CRT_PATH" -days 825 \
  -subj "/CN=${DOMAIN}" \
  -addext "subjectAltName=DNS:${DOMAIN}"

chmod 600 "$KEY_PATH"

echo "[gen_self_signed_cert] 생성 완료:"
echo "  $CRT_PATH"
echo "  $KEY_PATH"
echo "[gen_self_signed_cert] 브라우저는 신뢰하지 않는 인증서로 표시됩니다(임시/개발용)."
echo "[gen_self_signed_cert] 운영 배포에서는 사내 PKI 발급 인증서로 같은 파일명으로 교체하세요."
