"""
과거 인력현황 대량 소급 백필(scripts/backfill_team_refer_history.py,
skip_tombstone=True로 실행)이 끝난 뒤, 그 기간 중 실제로 사라진(조직
개편/명칭 변경 등) 조직들이 한 번도 톰스톤(deleted='Y')되지 않아
"현재" 판정(dep_id별 전체 파일 기준 가장 최근 날짜)에서 계속 "살아있음"
으로 오인되는 문제를 사후에 바로잡는 일회성 스크립트(2026-09-17).

── 문제 ────────────────────────────────────────────────────────────────────
관리자 화면 그리드(list_editable_rows())는 dep_id별로 "전체 파일에서
가장 최근 날짜의 행"을 "현재"로 보여준다. 2020년에 조직개편으로
사라진 옛날 조직이 있어도, 그 이후로 한 번도 톰스톤되지 않았다면
"이 조직의 현재 상태 = 2020년 마지막 값, deleted='N'"으로 계속 남아
그리드에 나타난다. 소급 백필이 process(skip_tombstone=True)로 실행돼
매달 "이번 달엔 왜 없어졌는지" 표시를 전혀 안 했기 때문이다.

── 해결 방식 ────────────────────────────────────────────────────────────────
team_refer.csv에 실제로 존재하는 시점(valid_year/month/day 조합)을
날짜 오름차순으로 나열한 뒤, 연속된 두 시점(Di, Di+1) 사이를 훑는다.
Di 시점에 deleted='N'으로 살아있던 dep_id인데 Di+1 시점에 그 dep_id
행 자체가 아예 없으면(다음 시점에 있으면 살아있든 이미 톰스톤됐든
그대로 둠 — 멱등적) 그 dep_id에 대해 Di+1 날짜로 새 톰스톤 행을
추가한다 — 값은 Di 시점 값을 그대로 보존하고 deleted만 'Y'로 바꾼다
(process_team_refer.tombstone_missing_dep_ids()가 정상 업로드마다
하는 것과 완전히 동일한 원리를 이력 전체에 사후 적용).

**기존 행은 절대 수정하지 않는다** — 새 톰스톤 행만 추가한다. 그래서
그 조직이 실제로 존재했던 과거 시점을 조회하는 데는 전혀 영향이 없다
(예: 2019년에 존재했다가 2020년 초에 사라진 조직 → 2019년 기간 지정
조회는 여전히 정상적으로 그 조직을 보여주고, 톰스톤은 2020년 초
시점에만 붙는다).

기본은 파일 전체(모든 시점)를 대상으로 하지만, --start/--end로 톰스톤을
붙일 "다음 시점" 범위를 제한할 수도 있다(둘 다 생략하면 전체 처리 —
이미 정상 처리된 구간은 "다음 시점에 이미 행이 있음" 조건으로 자동
스킵되니 전체를 대상으로 해도 안전하다).

사용법:
  python scripts/reconcile_team_refer_tombstones.py                (미리보기: 몇 건이 새로 톰스톤될지만 보여줌)
  python scripts/reconcile_team_refer_tombstones.py --apply         (실제로 반영, 반영 전 자동 백업)
  python scripts/reconcile_team_refer_tombstones.py --apply --start 2018-05-01 --end 2026-08-31
"""
import argparse
import csv
import os
import shutil
import sys
from datetime import date, datetime

import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
sys.path.insert(0, os.path.join(BASE_DIR, 'pipeline'))

from paths import OUT_DIR  # noqa: E402
from team_hierarchy import FIELDS  # noqa: E402

CSV_PATH = os.path.join(OUT_DIR, 'team_refer.csv')


def _date_key(row) -> tuple:
    return (str(row.get('valid_year', '')), str(row.get('valid_month', '')), str(row.get('valid_day', '')))


def _to_date(key: tuple) -> date:
    y, m, d = key
    return date(int(y), int(m), int(d))


def plan(df: pd.DataFrame, start: date | None, end: date | None) -> list[dict]:
    """반환: 새로 추가할 톰스톤 행 목록(자연키 포함 완성된 dict)."""
    by_date: dict[tuple, dict[str, dict]] = {}
    for _, row in df.iterrows():
        key = _date_key(row)
        by_date.setdefault(key, {})[row['dep_id']] = row.to_dict()

    dates = sorted(by_date.keys())
    new_tombstones = []
    for i in range(len(dates) - 1):
        d_prev, d_next = dates[i], dates[i + 1]
        next_date_obj = _to_date(d_next)
        if start and next_date_obj < start:
            continue
        if end and next_date_obj > end:
            continue

        prev_rows = by_date[d_prev]
        next_rows = by_date[d_next]
        for dep_id, row in prev_rows.items():
            if str(row.get('deleted', '')).strip().upper() == 'Y':
                continue  # 이미 죽어 있던 행은 대상 아님
            if dep_id in next_rows:
                continue  # 다음 시점에 이미 행이 있음(살아있거나 이미 톰스톤됨) — 스킵
            tomb = {c: row.get(c, '') for c in FIELDS}
            tomb['dep_id'] = dep_id
            tomb['valid_year'], tomb['valid_month'], tomb['valid_day'] = d_next
            tomb['deleted'] = 'Y'
            new_tombstones.append(tomb)
    return new_tombstones


def run(start_s: str | None, end_s: str | None, apply: bool) -> None:
    if not os.path.exists(CSV_PATH):
        print(f'[안내] {CSV_PATH} 파일이 없습니다.')
        return

    start = date.fromisoformat(start_s) if start_s else None
    end = date.fromisoformat(end_s) if end_s else None

    df = pd.read_csv(CSV_PATH, encoding='utf-8-sig', dtype=str).fillna('')
    missing_cols = [c for c in ('dep_id', 'valid_year', 'valid_month', 'valid_day', 'deleted') if c not in df.columns]
    if missing_cols:
        print(f'[ERROR] 필수 컬럼 없음(구버전 스키마?): {missing_cols}')
        return

    tombstones = plan(df, start, end)
    print(f'전체 {len(df)}행 중 새로 톰스톤될 조직: {len(tombstones)}건')
    by_next_date: dict[tuple, int] = {}
    for t in tombstones:
        key = (t['valid_year'], t['valid_month'], t['valid_day'])
        by_next_date[key] = by_next_date.get(key, 0) + 1
    for (y, m, d), count in sorted(by_next_date.items()):
        print(f'  {y}-{m}-{d}: {count}건')
    for t in tombstones[:15]:
        print(f"    · dep_id={t['dep_id']} org_name_wd={t.get('org_name_wd')!r} "
              f"→ {t['valid_year']}-{t['valid_month']}-{t['valid_day']}부터 삭제 처리")
    if len(tombstones) > 15:
        print(f'    ... 외 {len(tombstones) - 15}건 더')

    if not apply:
        print('\n[미리보기 모드] 실제로 반영하지 않았습니다. 반영하려면 --apply를 붙여 다시 실행하세요.')
        return

    if not tombstones:
        print('\n추가할 톰스톤이 없어 파일을 그대로 둡니다.')
        return

    backup_path = CSV_PATH + f'.bak-{datetime.now().strftime("%Y%m%d%H%M%S")}'
    shutil.copy2(CSV_PATH, backup_path)

    tomb_df = pd.DataFrame(tombstones, columns=list(FIELDS) + ['valid_year', 'valid_month', 'valid_day', 'deleted'])
    merged = pd.concat([df, tomb_df], ignore_index=True)
    merged.to_csv(CSV_PATH, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)
    print(f'\n[OK] {CSV_PATH}에 톰스톤 {len(tombstones)}건을 추가했습니다(원본 백업: {backup_path}).')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--apply', action='store_true', help='실제로 반영(기본값은 미리보기만)')
    parser.add_argument('--start', default=None, help='톰스톤을 붙일 "다음 시점"의 하한(YYYY-MM-DD, 생략 시 전체)')
    parser.add_argument('--end', default=None, help='톰스톤을 붙일 "다음 시점"의 상한(YYYY-MM-DD, 생략 시 전체)')
    args = parser.parse_args()
    run(args.start, args.end, args.apply)
