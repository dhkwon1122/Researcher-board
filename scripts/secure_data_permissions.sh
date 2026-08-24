#!/usr/bin/env bash
# data/ 디렉터리 전체(raw, raw_csv, processed 등)를 소유자만 읽고 쓸 수
# 있게 권한을 좁힌다.
#
# 배경: pipeline/process_*.py가 만드는 data/processed/*.csv(및 원천
# data/raw*, data/raw_csv/*)는 앱의 역할별 접근 제어(services/auth.py의
# ROLE_PERMISSIONS)와 무관하게, 서버에 셸 계정이 있는 사람이면 파일 권한이
# 열려 있는 한 누구나 그냥 열어볼 수 있다 — 역할별 접근 제어는 Dash/Flask
# 화면을 거칠 때만 적용되는 애플리케이션 레벨 제어라, 파일시스템 자체는
# 그 개념을 모르기 때문이다. pandas to_csv()가 만드는 파일은 보통 서버
# 기본 umask(흔히 644 — 소유자 외에도 읽기 가능)로 생성되므로, 운영
# 서버에서는 배포 때마다(또는 파이프라인 실행 후) 이 스크립트로 명시적으로
# 잠가둘 것.
#
# 소유권(chown)은 배포 환경마다 실행 계정이 달라 이 스크립트가 임의로
# 바꾸지 않는다 — data/ 가 이미 올바른 소유자(앱을 구동하는 계정)로 돼
# 있다고 가정하고 권한 비트만 좁힌다. 소유자가 다르면 이 스크립트 실행
# 전에 먼저 chown부터 맞출 것 — docker compose로 띄우는 경우엔
# scripts/fix_data_ownership.sh 로 컨테이너의 non-root app 유저(uid 10001)
# 소유로 맞춘다.
#
# 사용법:
#   scripts/secure_data_permissions.sh [데이터_루트_경로]
#   경로를 생략하면 이 스크립트 기준 ../data (저장소의 기본 data/ 위치).
#
#   docker compose 환경이면 호스트 쪽 ./data 에 대해 실행한다(컨테이너가
#   ./data:/app/data 로 바인드 마운트하므로, 실제 파일은 호스트에 있음).

set -euo pipefail

DATA_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/data}"

if [ ! -d "$DATA_DIR" ]; then
  echo "[secure_data_permissions] 데이터 디렉터리가 없습니다: $DATA_DIR" >&2
  exit 1
fi

echo "[secure_data_permissions] 대상: $DATA_DIR"
find "$DATA_DIR" -type d -exec chmod 700 {} +
find "$DATA_DIR" -type f -exec chmod 600 {} +
echo "[secure_data_permissions] 완료 — 소유자 외 읽기/쓰기/실행 권한을 모두 제거했습니다."
