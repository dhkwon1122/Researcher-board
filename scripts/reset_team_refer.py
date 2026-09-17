"""
team_refer.csv(+DB team_refer 테이블)를 통째로 비우는 일회성 초기화
스크립트(2026-09-17, 사용자 요청) — "기존 모든 데이터를 지우고(모든 근본
원인 삭제) 처음부터 데이터를 업로드하고 싶다".

왜 필요한가: dep_id는 1/2/3단계부서명 "전체 경로" 텍스트에서 결정적으로
계산되는데(team_hierarchy.py 참고), 그리드 왕복 버그(수정 전 —
backfill_full_path()가 재배치된 칸을 그대로 믿어 own_path()가 빈 칸 없는
값을 다단계 경로로 오인)로 인해 실제로는 존재하지 않는 "유령 dep_id"가
과거에 이미 CSV/DB에 저장된 경우가 있다. 이 유령 dep_id는 이후 정상
업로드를 아무리 반복해도 "이번 업로드에 없는 옛 dep_id"로 자동 톰스톤
처리돼야 정상인데, 실제로 org_name_wd/upper_dep_id 조합에 따라 계속
"현재"로 오인될 수 있어(2D/NAND처럼 하위 조직이 없는 2단계 조직에서
재현) 코드만 고쳐서는 이미 쌓인 유령 데이터가 자동으로 정리되지
않는다. 근본 원인을 찾아 개별적으로 지우는 대신, 이번 기회에 team_refer
데이터를 통째로 비우고 최신 팀참조시트.xlsx를 한 번에 다시 업로드해
"현재 실제로 존재하는 조직만 깨끗하게" 다시 쌓는 방향으로 정리한다.

**영향 범위**: team_refer.csv(조직도 전용 테이블)와 DB team_refer 테이블
만 지운다 — researchers.csv 등 다른 테이블에는 전혀 영향 없다. team_refer가
비어 있는 동안에는 "보유 전문성"(조직도) 관련 화면만 빈 화면으로 보이고,
그 외 화면(연구원 명단/프로필 등)은 정상 동작한다(team_refer는 조직도
전용이라 다른 화면이 이 테이블에 강하게 의존하지 않음 — 다시 업로드하면
바로 정상화된다).

**날짜 이력(valid_year/month/day별 과거 스냅샷)도 전부 사라진다** — 이번
초기화 이후로는 새로 쌓이는 이력만 남는다. 과거 조직 변경 이력 조회가
필요 없다는 전제(사용자 확정)로 진행.

data/processed/team_leader_refer/ 아래의 날짜별 xlsx 스냅샷(그리드
"저장" 시 남기는 아카이브 파일)은 건드리지 않는다 — 이건 team_refer.csv
와 별개의 백업 파일이라 원인 정리와 무관.

사용법:
  python scripts/reset_team_refer.py                 (미리보기: 뭘 지울지만 보여줌, 실제로 안 지움)
  python scripts/reset_team_refer.py --apply          (CSV 백업 후 실제로 비움)
  python scripts/reset_team_refer.py --apply --sync-db  (DB team_refer 테이블도 전부 삭제)

CSV는 파일 자체를 지우지 않고 헤더만 남기고 데이터 행을 전부 비우는
방식으로 처리한다(백업 파일을 먼저 반드시 만들고, 그 다음 빈 파일로
교체) — 지운 뒤에 "역시 필요했다"는 걸 알게 되도 원본을 복구할 수 있게.
"""
import argparse
import csv
import os
import shutil
import sys
from datetime import datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'pipeline'))

from paths import OUT_DIR  # noqa: E402
from team_hierarchy import FIELDS  # noqa: E402

CSV_PATH = os.path.join(OUT_DIR, 'team_refer.csv')
_ALL_COLUMNS = list(FIELDS) + ['valid_year', 'valid_month', 'valid_day', 'deleted']


def main(apply: bool, sync_db: bool) -> None:
    if not os.path.exists(CSV_PATH):
        print(f'[안내] {CSV_PATH} 파일이 없습니다 — 지울 CSV 데이터가 없습니다.')
        csv_rows = 0
    else:
        df = pd.read_csv(CSV_PATH, encoding='utf-8-sig', dtype=str).fillna('')
        csv_rows = len(df)
        print(f'{CSV_PATH}: {csv_rows}행 (전부 삭제 대상)')

    db_rows = None
    if sync_db or not apply:
        sys.path.insert(0, BASE_DIR)
        from services.team_refer_store import available, get_engine, team_refer
        if available():
            from sqlalchemy import func, select
            with get_engine().connect() as conn:
                db_rows = conn.execute(select(func.count()).select_from(team_refer)).scalar()
            print(f'DB team_refer 테이블: {db_rows}행 (전부 삭제 대상, --sync-db일 때만 실제 삭제)')
        else:
            print('[안내] DATABASE_URL이 설정돼 있지 않거나 DB에 연결할 수 없습니다(DB 삭제는 건너뜀).')

    if not apply:
        print('\n[미리보기 모드] 실제로 지우지 않았습니다. 반영하려면 --apply를 붙여 다시 실행하세요.')
        return

    if csv_rows:
        backup_path = CSV_PATH + f'.bak-{datetime.now().strftime("%Y%m%d%H%M%S")}'
        shutil.copy2(CSV_PATH, backup_path)
        empty = pd.DataFrame(columns=_ALL_COLUMNS)
        empty.to_csv(CSV_PATH, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        print(f'[OK] {CSV_PATH}를 비웠습니다(원본 백업: {backup_path}).')
    else:
        print('[안내] CSV에 지울 행이 없어 그대로 둡니다.')

    if sync_db:
        from services.team_refer_store import available, get_engine, team_refer
        if not available():
            print('[안내] DATABASE_URL이 설정돼 있지 않거나 DB에 연결할 수 없어 DB 삭제를 건너뜁니다.')
        else:
            with get_engine().begin() as conn:
                conn.execute(team_refer.delete())
            print('[OK] DB team_refer 테이블을 비웠습니다.')

    print('\n이제 관리자 화면 "팀/리더 참조" 탭 → "엑셀 파일로 한번에 반영"에서 '
          '최신 팀참조시트.xlsx를 다시 업로드하면 현재 조직만 깨끗하게 새로 쌓입니다.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='실제로 비움(기본값은 미리보기만)')
    parser.add_argument('--sync-db', action='store_true',
                         help='DB team_refer 테이블도 함께 비움(DATABASE_URL 설정 환경 전용)')
    args = parser.parse_args()
    main(apply=args.apply, sync_db=args.sync_db)
