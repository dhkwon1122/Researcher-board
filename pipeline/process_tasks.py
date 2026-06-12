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
    """투입률 → 정수 문자열(%). 알 수 없으면 빈 문자열."""
    try:
        s = str(val).strip()
        if s.lower() in ('', 'nan', 'none', 'nat'):
            return ''
        v = float(s)
        if 0.0 < v <= 1.0:
            v = round(v * 100)
        return str(int(round(v)))
    except (TypeError, ValueError):
        return ''


_EMPTY = {'', 'nan', 'none', 'nat'}


def _merge_consecutive_periods(df: pd.DataFrame) -> pd.DataFrame:
    """같은 (researcher_id, task_name) 내에서
    종료일 == 다음 시작일인 연속 구간을 하나로 병합.
    병합 시 최초 시작일 · 마지막 종료일 사용, 투입률은 최신 값.
    """
    result = []
    for (rid, task), grp in df.groupby(['researcher_id', 'task_name'], sort=False):
        grp = grp.sort_values('start_date').reset_index(drop=True)

        cur_s = str(grp.iloc[0]['start_date']).strip()
        cur_e = str(grp.iloc[0]['end_date']).strip()
        cur_r = str(grp.iloc[0]['input_rate']).strip()
        if cur_e.lower() in _EMPTY:
            cur_e = ''

        for i in range(1, len(grp)):
            ns = str(grp.iloc[i]['start_date']).strip()
            ne = str(grp.iloc[i]['end_date']).strip()
            nr = str(grp.iloc[i]['input_rate']).strip()
            if ne.lower() in _EMPTY:
                ne = ''

            # 연속 조건: 이전 종료일 == 다음 시작일
            if cur_e != '' and ns == cur_e:
                cur_e = ne   # '' (ongoing) 또는 더 늦은 날짜
                cur_r = nr
            else:
                result.append({'researcher_id': rid, 'task_name': task,
                                'start_date': cur_s, 'end_date': cur_e, 'input_rate': cur_r})
                cur_s, cur_e, cur_r = ns, ne, nr

        result.append({'researcher_id': rid, 'task_name': task,
                       'start_date': cur_s, 'end_date': cur_e, 'input_rate': cur_r})

    if not result:
        return pd.DataFrame(columns=['researcher_id', 'task_name',
                                     'start_date', 'end_date', 'input_rate'])
    return pd.DataFrame(result)


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

    result = result[result['researcher_id'] != ''].reset_index(drop=True)

    # 연속 수행기간 병합
    result = _merge_consecutive_periods(result)
    result = result.sort_values(['researcher_id', 'start_date']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    result.to_csv(OUTPUT, index=False, encoding='utf-8-sig')
    print(f'[process_tasks] 저장 완료: {OUTPUT}  ({len(result)}행)')


if __name__ == '__main__':
    process()
