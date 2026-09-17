"""
기존 저장된 team_refer.csv(+DB team_refer 테이블)에 이미 쌓인 데이터를,
pipeline.process_team_refer.reshape_storage_columns()가 새로 도입한 저장
형식(2026-09-17 확정 — org_name_wd는 무조건 3단계부서명 칸에, 그보다 얕은
조직은 조상 이름을 1·2단계 칸에 채움)으로 한 번에 맞추는 일회성 마이그레이션
스크립트.

왜 필요한가: reshape_storage_columns()는 process()(xlsx 일괄 업로드)/
save_snapshot()(그리드 저장) 양쪽에 붙여놨지만, "다음 저장부터" 새 형식으로
쓰일 뿐 이미 파일에 쌓여 있는 과거 행에는 소급 적용되지 않는다. 외부 시스템은
team_refer.csv를 통째로 직접 읽으므로, 이 스크립트를 한 번 돌려 기존 행도
전부 같은 형식으로 맞춰야 한다.

날짜별로 나눠 처리하는 이유: team_refer.csv는 (dep_id, valid_year,
valid_month, valid_day) 자연키로 계속 누적되는 이력형 테이블이라(pipeline/
merge_utils.py TABLE_KEYS['team_refer'] 참고), 같은 파일 안에 서로 다른
시점의 "조직 전체 스냅샷"이 여러 벌 들어있다 — process()/save_snapshot()이
매번 "그 시점의 현재 조직 전체"를 그 날짜로 통째로 저장하기 때문에(부분
패치가 아님), 같은 (valid_year, valid_month, valid_day) 값을 가진 행들만
모으면 그 자체로 완결된 하나의 조직 트리가 된다. 그래서 이 스크립트도
날짜별로 행을 묶어 그 그룹 안에서만 reshape_storage_columns()의 dep_id ↔
upper_dep_id 조상 조회를 수행한다 — 서로 다른 날짜의 트리를 섞어서 조회하면
그 시점엔 존재하지 않았던 조직 구조가 섞여 들어갈 수 있기 때문.

deleted='Y'(톰스톤) 행은 건드리지 않는다: 톰스톤은 "그 조직이 사라지기 직전
마지막으로 알려진 값"을 그대로 보존만 하는 행이라(tombstone_missing_dep_ids()
docstring 참고), 톰스톤이 찍힌 시점의 조직 트리 전체가 같은 날짜 그룹 안에
함께 있다는 보장이 없다(다른 조직이 사라져 생긴 톰스톤이 이번 그룹에 섞여
있을 뿐, 그 조상 체인이 이번 그룹에 다 있으리라는 보장이 없음) — 무리해서
조회하면 조상을 못 찾아 오히려 있던 라벨을 지우는 회귀가 생길 수 있어
안전하게 원래 값을 그대로 둔다(어차피 deleted='Y'라 "현재" 조직도/그리드
어디서도 읽히지 않는 죽은 행).

사용법:
  python scripts/migrate_team_refer_reshape.py                 (미리보기만, 저장 안 함)
  python scripts/migrate_team_refer_reshape.py --apply          (실제로 파일에 반영)
  python scripts/migrate_team_refer_reshape.py --apply --sync-db (반영 후 DB team_refer
                                                                   테이블에도 동일하게 upsert
                                                                   — DATABASE_URL이 설정된
                                                                   운영 환경에서, DB에도 이미
                                                                   과거 데이터가 적재돼 있는
                                                                   경우에만 필요)

--apply 없이 실행하면 몇 행이 바뀔지, 바뀌는 예시 몇 개만 보여주고 파일은
그대로 둔다(사용자가 먼저 결과를 확인할 수 있도록). 실제 반영 시 원본을
team_refer.csv.bak-<타임스탬프>로 먼저 백업해 둔다(되돌릴 수 있도록).
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

import process_team_refer as ptr  # noqa: E402
from paths import OUT_DIR  # noqa: E402

_LEVEL_COLS = ('dep_1st_name', 'dep_2nd_name', 'dep_3rd_name')
CSV_PATH = os.path.join(OUT_DIR, 'team_refer.csv')


def _reshape_csv(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """df(team_refer.csv 전체, deleted 포함)를 (valid_year, valid_month,
    valid_day) 그룹별로 reshape_storage_columns()를 적용해 반환한다.
    deleted=='Y'인 톰스톤 행은 건드리지 않는다(모듈 docstring 참고).

    반환: (재배치된 전체 df, 실제로 값이 바뀐 행의 [{...전/후 비교...}] 목록)."""
    result = df.copy()
    changes: list[dict] = []
    live_mask = result['deleted'] != 'Y'

    group_keys = ['valid_year', 'valid_month', 'valid_day']
    for _, idx in result[live_mask].groupby(group_keys).groups.items():
        group = result.loc[idx]
        reshaped = ptr.reshape_storage_columns(group)
        for col in _LEVEL_COLS:
            result.loc[idx, col] = reshaped[col]

    for i in df.index:
        before = tuple(df.loc[i, c] for c in _LEVEL_COLS)
        after = tuple(result.loc[i, c] for c in _LEVEL_COLS)
        if before != after:
            changes.append({
                'dep_id': df.loc[i, 'dep_id'],
                'org_name_wd': df.loc[i, 'org_name_wd'],
                'valid_date': f"{df.loc[i, 'valid_year']}-{df.loc[i, 'valid_month']}-{df.loc[i, 'valid_day']}",
                'before': before,
                'after': after,
            })
    return result, changes


def main(apply: bool, sync_db: bool) -> None:
    if not os.path.exists(CSV_PATH):
        print(f'[안내] {CSV_PATH} 파일이 없습니다.')
        return

    df = pd.read_csv(CSV_PATH, encoding='utf-8-sig', dtype=str).fillna('')
    missing = [c for c in list(_LEVEL_COLS) + ['dep_id', 'upper_dep_id', 'team_layer', 'org_name_wd', 'deleted',
                                                'valid_year', 'valid_month', 'valid_day'] if c not in df.columns]
    if missing:
        print(f'[ERROR] 필수 컬럼 없음(구버전 스키마?): {missing}')
        return

    result, changes = _reshape_csv(df)

    print(f'전체 {len(df)}행 중 {len(changes)}행의 1·2·3단계부서명이 바뀝니다.')
    for c in changes[:15]:
        print(f"  · [{c['valid_date']}] dep_id={c['dep_id']} (org_name_wd={c['org_name_wd']}) "
              f"{c['before']} → {c['after']}")
    if len(changes) > 15:
        print(f'  ... 외 {len(changes) - 15}행 더')

    if not apply:
        print('\n[미리보기 모드] 실제 파일은 바꾸지 않았습니다. 반영하려면 --apply를 붙여 다시 실행하세요.')
        return

    if not changes:
        print('\n바뀔 행이 없어 파일을 다시 쓰지 않습니다.')
    else:
        backup_path = CSV_PATH + f'.bak-{datetime.now().strftime("%Y%m%d%H%M%S")}'
        shutil.copy2(CSV_PATH, backup_path)
        result.to_csv(CSV_PATH, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
        print(f'\n[OK] {CSV_PATH}에 반영했습니다(원본 백업: {backup_path}).')

    if sync_db:
        sys.path.insert(0, BASE_DIR)
        from services.team_refer_store import _upsert_rows_to_db, available
        if not available():
            print('[안내] DATABASE_URL이 설정돼 있지 않거나 DB에 연결할 수 없어 --sync-db를 건너뜁니다.')
            return
        ok = _upsert_rows_to_db(result)
        print(f"[{'OK' if ok else 'WARN'}] DB team_refer 테이블 동기화 {'성공' if ok else '실패(CSV는 이미 반영됨)'}")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='실제로 team_refer.csv에 반영(기본값은 미리보기만)')
    parser.add_argument('--sync-db', action='store_true',
                         help='반영 후 DB team_refer 테이블에도 동일하게 upsert(DATABASE_URL 설정 환경 전용)')
    args = parser.parse_args()
    main(apply=args.apply, sync_db=args.sync_db)
