"""
과제 수행 이력 전처리
Source : data/raw/개인별과제투입기간데이터_260114.xlsb
Output : data/processed/tasks.csv

컬럼 매핑:
  KNOXID → researcher_id (8자리 제로패딩)
  과제명  → task_name
  시작일  → start_date  (YYYYMMDD → YYYY-MM-DD)
  해제일  → end_date    (YYYYMMDD → YYYY-MM-DD)
  투입률  → input_rate  (정수 %)
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR  = os.path.join(BASE_DIR, 'data', 'raw')
OUT_DIR  = os.path.join(BASE_DIR, 'data', 'processed')

SOURCE = os.path.join(RAW_DIR, '개인별과제투입기간데이터_260114.xlsb')
OUTPUT = os.path.join(OUT_DIR, 'tasks.csv')

COL_ID    = 'KNOXID'
COL_TASK  = '과제명'
COL_START = '시작일'
COL_END   = '해제일'
COL_RATE  = '투입률'


def _parse_date(val) -> str:
    """YYYYMMDD(숫자 or 문자열) → YYYY-MM-DD. 변환 불가 시 빈 문자열."""
    if val is None:
        return ''
    s = str(val).strip().split('.')[0]  # 20230101.0 처리
    if s in ('', 'nan', 'None', 'NaT'):
        return ''
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:]}'
    return s


def _parse_rate(val) -> str:
    """투입률 → 정수 문자열(%).
    0~1 소수(0.5 → 50), 정수(50 → 50), 100 초과 클램프.
    """
    try:
        v = float(str(val).strip())
        if 0.0 < v <= 1.0:
            v = round(v * 100)
        return str(int(round(v)))
    except (TypeError, ValueError):
        return ''


def process():
    from excel_reader import norm_id, read_xlsx

    if not os.path.exists(SOURCE):
        print(f'[process_tasks] 파일 없음: {SOURCE}')
        return

    print(f'[process_tasks] 읽는 중: {SOURCE}')
    df = read_xlsx(SOURCE)

    missing = [c for c in [COL_ID, COL_TASK, COL_START, COL_END, COL_RATE]
               if c not in df.columns]
    if missing:
        print(f'[process_tasks] 컬럼 없음: {missing}')
        print(f'  실제 컬럼: {list(df.columns)}')
        return

    result = pd.DataFrame({
        'researcher_id': df[COL_ID].apply(norm_id),
        'task_name':     df[COL_TASK].astype(str).str.strip(),
        'start_date':    df[COL_START].apply(_parse_date),
        'end_date':      df[COL_END].apply(_parse_date),
        'input_rate':    df[COL_RATE].apply(_parse_rate),
    })

    result = (result[result['researcher_id'] != '']
              .sort_values(['researcher_id', 'start_date'])
              .reset_index(drop=True))

    os.makedirs(OUT_DIR, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
    print(f'[process_tasks] 저장 완료: {OUTPUT}  ({len(result)}행)')


if __name__ == '__main__':
    process()
