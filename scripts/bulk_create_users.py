"""
피플팀 계정을 CSV/xlsx 명단으로 한 번에 만드는 스크립트.

모든 계정은 동일한 임시 비밀번호로 생성되고 must_change_password=True 상태로
시작한다 — 그 계정으로 처음 로그인하면(services/auth.py, app.py의
require_login 미들웨어) 다른 화면으로 못 가고 /change-password 에서 본인이
비밀번호를 새로 설정해야 이후 접근이 풀린다.

계정은 DATABASE_URL이 설정돼 있으면 PostgreSQL(app_users 테이블)에, 아니면
config/users.json에 저장된다 — services/auth.create_user()를 그대로 호출하므로
백엔드 선택은 이 스크립트가 신경 쓸 필요가 없다.

입력 파일 컬럼(순서 무관, 헤더 이름으로 찾음):
  아이디 (또는 user_id)      : 로그인 아이디(사번 등). 필수, 중복 불가.
  이름   (또는 display_name) : 표시 이름. 필수.
  이메일 (또는 email)        : 선택.
  권한   (또는 role)         : config/auth_config.py의 ROLE_LABELS에 등록된
                               역할 코드(예: talent_dev) 또는 한글 라벨(예:
                               인재개발 담당자) 둘 다 허용. 필수.
  관리자 (또는 is_admin)     : 선택. Y/TRUE/1/O/예 중 하나면 사용자 관리
                               페이지(manage_users) 접근 권한을 개인별로
                               부여한다(역할과 무관 — config/auth_config.py
                               참고). 비워두면 관리자 아님(기본값).

사용법:
  cp scripts/bulk_create_users.example.csv scripts/people_team_users.csv
  (파일을 열어 실제 명단으로 채운 뒤)

  # 먼저 미리보기(실제로 계정을 만들지 않음)
  python scripts/bulk_create_users.py scripts/people_team_users.csv \
      --temp-password 'Temp1234!' --dry-run

  # 문제없으면 실제 생성
  python scripts/bulk_create_users.py scripts/people_team_users.csv \
      --temp-password 'Temp1234!'

  # --temp-password 를 생략하면 터미널에 안 보이게 입력받는다(getpass).
  python scripts/bulk_create_users.py scripts/people_team_users.csv

docker compose로 띄운 환경에서 DB에 바로 넣으려면 컨테이너 안에서 실행한다:
  docker compose exec app python scripts/bulk_create_users.py \
      scripts/people_team_users.csv --temp-password 'Temp1234!'
"""

import argparse
import getpass
import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config.auth_config import ROLE_LABELS  # noqa: E402
from services.auth import create_user, list_users, password_validation_error  # noqa: E402
from services.bulk_user_import import parse_rows, read_upload  # noqa: E402


def _read_input(path: str) -> pd.DataFrame:
    with open(path, 'rb') as f:
        return read_upload(f.read(), path)


def main():
    parser = argparse.ArgumentParser(description='피플팀 계정 일괄 생성')
    parser.add_argument('input_file', help='계정 명단 CSV/xlsx 경로')
    parser.add_argument('--temp-password', help='전 계정 공통 임시 비밀번호(8~12자, 영문/숫자/특수문자 조합). '
                                                  '생략하면 안전하게 입력받는다.')
    parser.add_argument('--dry-run', action='store_true',
                        help='실제로 계정을 만들지 않고 무엇이 처리될지만 보여준다.')
    args = parser.parse_args()

    temp_password = args.temp_password or getpass.getpass('임시 비밀번호(8~12자, 영문/숫자/특수문자 조합, 전 계정 공통): ')
    password_error = password_validation_error(temp_password)
    if password_error:
        print(f'[오류] {password_error}')
        sys.exit(1)

    df = _read_input(args.input_file)
    existing_ids = {u['user_id'] for u in list_users()}
    result = parse_rows(df, existing_ids)

    if result['missing_columns']:
        print(f"[오류] 필수 컬럼을 찾을 수 없습니다: {', '.join(result['missing_columns'])}")
        print(f'  파일의 컬럼: {list(df.columns)}')
        sys.exit(1)

    created = result['rows']
    skipped_existing = result['skipped_existing']
    skipped_invalid = result['skipped_invalid']

    print(f'입력 {len(df)}행 → 생성 대상 {len(created)}명, '
          f'이미 존재해서 건너뜀 {len(skipped_existing)}명, '
          f'형식 오류로 건너뜀 {len(skipped_invalid)}명')

    if skipped_existing:
        print(f'  이미 존재: {", ".join(skipped_existing)}')
    for uid, reason in skipped_invalid:
        print(f'  [건너뜀] {uid}: {reason}')

    if args.dry_run:
        print('\n--dry-run 이므로 실제로 계정을 만들지 않았습니다. 아래 목록을 확인하세요:')
        for u in created:
            admin_tag = ' [관리자]' if u['is_admin'] else ''
            print(f"  {u['user_id']:<15} {u['display_name']:<10} "
                  f"{ROLE_LABELS.get(u['role'], u['role']):<14} {u['email']}{admin_tag}")
        return

    ok, failed = [], []
    for u in created:
        try:
            create_user(u['user_id'], temp_password, u['display_name'], u['role'],
                        u['email'], must_change_password=True, is_admin=u['is_admin'])
            ok.append(u['user_id'])
        except Exception as exc:
            failed.append((u['user_id'], str(exc)))

    print(f'\n생성 완료: {len(ok)}명')
    if failed:
        print(f'생성 실패: {len(failed)}명')
        for uid, err in failed:
            print(f'  {uid}: {err}')

    if ok:
        print('\n생성된 계정은 모두 같은 임시 비밀번호로 로그인 가능하며, '
              '로그인 직후 비밀번호를 새로 설정하기 전까지는 다른 화면에 접근할 수 없습니다. '
              '임시 비밀번호를 안전한 방법으로 대상자들에게 전달하세요.')


if __name__ == '__main__':
    main()
