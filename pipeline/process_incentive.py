"""
인센티브 선정 이력 처리 모듈

원천 파일: data/raw/핵심이력.xlsx
출력 파일: data/processed/incentive_selection.csv

읽는 컬럼:
  사번, 26, 25, 24, 23, 22  (연도별 선정 구분)

컬럼 '22'~'26'은 연도 뒤 두 자리이며, 값이 있으면 선정(selected=True),
값이 없으면 미선정(selected=False)으로 기록합니다.
값 자체가 선정 구분명(category)으로 사용됩니다.

출력 스키마:
  researcher_id, year, selected, category, note

컬럼명이 다를 경우 파일 상단의 COL_* 상수를 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

INCENTIVE_FILE = '핵심이력.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID = '사번'
# 연도 컬럼: 뒤 두 자리 → 전체 연도 매핑 (추가/변경 가능)
YEAR_COLS = {'22': 2022, '23': 2023, '24': 2024, '25': 2025, '26': 2026}
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def _norm_col(c) -> str:
    """숫자형 헤더 '22.0' → '22' 정규화."""
    s = str(c).strip()
    try:
        f = float(s)
        if f == int(f):
            return str(int(f))
    except (ValueError, TypeError):
        pass
    return s


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, INCENTIVE_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {INCENTIVE_FILE} 파일 없음 — incentive_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [_norm_col(c) for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_incentive.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    # 연도 컬럼 중 실제로 존재하는 것만 사용
    avail = {col: yr for col, yr in YEAR_COLS.items() if col in df.columns}
    if not avail:
        print(
            f'[ERROR] 연도 컬럼을 찾을 수 없습니다.\n'
            f'  찾는 컬럼: {list(YEAR_COLS.keys())}\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    # 와이드 → 롱 변환
    rows = []
    for _, row in df.iterrows():
        for col, year in sorted(avail.items(), key=lambda x: x[1]):
            val = row.get(col, None)
            val_str = str(val).strip() if val is not None else ''
            if val_str in ('', 'nan', 'None', 'NaT'):
                selected = False
                category = ''
            else:
                selected = True
                category = val_str
            rows.append({
                'researcher_id': row['researcher_id'],
                'year':          year,
                'selected':      selected,
                'category':      category,
                'note':          '',
            })

    result = pd.DataFrame(rows, columns=['researcher_id', 'year', 'selected', 'category', 'note'])
    result = result.sort_values(['researcher_id', 'year']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'incentive_selection.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique()
    sel = int(result['selected'].sum())
    print(f'[OK]   incentive_selection.csv 저장 ({len(result)}행, {n}명, 선정 {sel}건)')
    return True


if __name__ == '__main__':
    process()
