#!/usr/bin/env bash
# ./data(호스트)의 소유권을 컨테이너 안 non-root app 유저(uid:gid 10001:10001,
# Dockerfile 참고)로 맞춘다.
#
# 배경: Dockerfile이 컨테이너를 root가 아니라 uid 10001(app)로 띄우도록
# 바꾼 뒤로(보안 강화), docker-compose.yml의 ./data:/app/data 바인드
# 마운트는 컨테이너 안에서도 호스트의 실제 소유권을 그대로 쓴다 — named
# volume(예: bge_hf_cache)과 달리 바인드 마운트는 Docker가 소유권을 자동
# 으로 맞춰주지 않는다. 호스트의 ./data가 uid 10001 소유가 아니면(대부분
# 그렇다 — 10001은 실제 로그인 계정이 아니므로) 앱이 data/processed/ 아래
# 쓰기 실패한다(예: "Permission denied:
# /app/data/processed/embedding_cache.json" — 사용자 리포트).
#
# 사용법:
#   sudo scripts/fix_data_ownership.sh [데이터_루트_경로]
#   경로를 생략하면 이 스크립트 기준 ../data (저장소의 기본 data/ 위치).
#   다른 uid로 소유권을 바꾸는 chown은 보통 root 권한이 필요해 sudo로
#   실행해야 한다.
#
#   docker compose 환경이면 호스트 쪽 ./data 에 대해 실행한다(컨테이너가
#   ./data:/app/data 로 바인드 마운트하므로, 실제 파일은 호스트에 있음).
#   scripts/secure_data_permissions.sh(권한 비트를 좁히는 스크립트)는 이미
#   올바른 소유자를 전제하므로, 이 스크립트를 먼저 실행한 뒤에 쓸 것.

set -euo pipefail

DATA_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data}"
APP_UID=10001
APP_GID=10001

if [ ! -d "$DATA_DIR" ]; then
  echo "[fix_data_ownership] 데이터 디렉터리가 없습니다: $DATA_DIR" >&2
  exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
  echo "[fix_data_ownership] root 권한이 필요합니다 — sudo로 실행하세요:" >&2
  echo "  sudo $0 $DATA_DIR" >&2
  exit 1
fi

echo "[fix_data_ownership] 대상: $DATA_DIR (소유권을 ${APP_UID}:${APP_GID}로 변경)"
chown -R "${APP_UID}:${APP_GID}" "$DATA_DIR"
echo "[fix_data_ownership] 완료. 컨테이너를 재시작할 필요는 없습니다(바인드 마운트라 즉시 반영됨)."
