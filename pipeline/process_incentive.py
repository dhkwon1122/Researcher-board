"""
인센티브 선정 이력 처리 모듈

원천: source_reader.read_source('incentive_selection')
  → DB incentive_selection_stg 테이블 또는 data/raw_csv/incentive_selection.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/핵심이력.xlsx를 DRM 제거해 만든 사본)
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

import os
import sys

import pandas as pd

INCENTIVE_FILE = '핵심이력.xlsx'
_INCENTIVE_HEADER_ROW = 0  # sources.py 매니페스트 기준 (1번째 행)

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID = '사번'
# 연도 컬럼: 뒤 두 자리 → 전체 연도 매핑 (추가/변경 가능)
YEAR_COLS = {'22': 2022, '23': 2023, '24': 2024, '25': 2025, '26': 2026}
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import is_blank, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source


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


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('incentive_selection')
        if df is None:
            print('[SKIP] incentive_selection 원천 데이터 없음 '
                  '(DB incentive_selection_stg 또는 data/raw_csv/incentive_selection.csv) — incentive_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, INCENTIVE_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path, header_row=_INCENTIVE_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {INCENTIVE_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False
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
            if is_blank(val_str):
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

    out_path = os.path.join(OUT_DIR, 'incentive_selection.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['incentive_selection'])

    n = merged['researcher_id'].nunique()
    sel = int(merged['selected'].astype(str).isin(['True', 'true', '1']).sum())
    print(f'[OK]   incentive_selection.csv 저장 (총 {len(merged)}행, {n}명, 선정 {sel}건, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
