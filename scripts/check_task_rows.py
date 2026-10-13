"""한 연구원의 과제참여이력 행을 파일(tasks.csv)과 DB(tasks 테이블) 양쪽에서 비교 출력(읽기 전용).

타임라인 과제 카드가 중복으로 보일 때 원인(파일 자체 중복 / 옛 과제명 행 잔존 / DB가 옛 사본) 확인용.
사용법: python scripts/check_task_rows.py <사번> [과제코드]
"""
import os
import sys

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

COLS = ['researcher_id', 'task_name', 'start_date', 'end_date', 'task_code', 'the_task_name']


def _show(label, df, rid, code):
    if df is None:
        print(f'\n[{label}] 없음')
        return
    df = df.fillna('').astype(str)
    df = df[df['researcher_id'].str.strip().str.zfill(8) == rid]
    if code:
        df = df[df['task_code'] == code] if 'task_code' in df.columns else df.iloc[0:0]
    cols = [c for c in COLS if c in df.columns]
    print(f'\n[{label}] {len(df)}행')
    if not df.empty:
        print(df[cols].sort_values('start_date').to_string(index=False))
        dup = df.duplicated(subset=[c for c in ('the_task_name', 'start_date', 'end_date') if c in df.columns], keep=False)
        if dup.any():
            print(f'  -> 같은 과제명·기간이 중복된 행 {int(dup.sum())}개')
            keys = [c for c in ('the_task_name', 'start_date', 'end_date') if c in df.columns]
            causes = set()
            for _, grp in df[dup].groupby(keys):
                diff = [c for c in grp.columns if grp[c].nunique() > 1]
                causes.add(', '.join(diff) if diff else '모든 열 동일')
            for c in sorted(causes):
                print(f'     중복 행끼리 값이 다른 열: {c}')


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    rid = sys.argv[1].strip().zfill(8)
    code = sys.argv[2].strip() if len(sys.argv) > 2 else ''
    path = os.path.join(BASE, 'data', 'processed', 'tasks.csv')
    _show('파일 data/processed/tasks.csv', pd.read_csv(path, dtype=str, encoding='utf-8-sig') if os.path.exists(path) else None,
          rid, code)
    try:
        from services.db import get_engine, load_env_file
        load_env_file()
        engine = get_engine()
    except Exception as exc:
        print(f'\n[DB] 접속 준비 실패: {exc}')
        return
    if engine is None:
        print('\n[DB] DATABASE_URL 미설정 — 앱은 파일을 읽음')
        return
    try:
        _show('DB tasks (앱이 실제로 읽는 쪽)', pd.read_sql_query('SELECT * FROM tasks', engine, dtype=str), rid, code)
    except Exception as exc:
        print(f'\n[DB] 조회 실패: {exc}')


if __name__ == '__main__':
    main()
