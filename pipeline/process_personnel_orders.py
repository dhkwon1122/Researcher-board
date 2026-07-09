"""
인사발령 이력 처리 모듈

원천 파일: data/raw/인사발령이력.xlsx
출력 파일: data/processed/hr_orders.csv

컬럼 매핑:
  사원번호 → researcher_id (8자리 제로패딩)
  발령일자(YYYYMMDD) → order_date (YYYY-MM-DD)
  발령명   → order_name
  부서     → order_dep
  직급명   → order_cl (괄호와 괄호 안 내용 제거, 예: '선임연구원(과장)' → '선임연구원')

컬럼 설정 (실제 파일 헤더에 맞게 상단 상수 수정):
  COL_ID   : 사원번호 컬럼명
  COL_DATE : 발령일자 컬럼명
  COL_NAME : 발령명 컬럼명
  COL_DEP  : 부서 컬럼명
  COL_CL   : 직급명 컬럼명
"""

import csv
import os
import re
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

ORDERS_FILE = '인사발령이력.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID   = '사원번호'
COL_DATE = '발령일자'
COL_NAME = '발령명'
COL_DEP  = '부서'
COL_CL   = '직급명'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id

_PAREN_RE = re.compile(r'[\(（][^)）]*[\)）]')


def _parse_date(val) -> str:
    """YYYYMMDD(숫자 or 문자열) → YYYY-MM-DD. 변환 불가 시 빈 문자열."""
    if val is None:
        return ''
    s = str(val).strip().split('.')[0]
    if s in ('', 'nan', 'None', 'NaT'):
        return ''
    if len(s) == 8 and s.isdigit():
        return f'{s[:4]}-{s[4:6]}-{s[6:]}'
    return s


def _strip_paren(val) -> str:
    """괄호와 괄호 안 내용 제거 (예: '선임연구원(과장)' → '선임연구원')."""
    s = str(val).strip()
    return _PAREN_RE.sub('', s).strip()


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, ORDERS_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {ORDERS_FILE} 파일 없음 — hr_orders_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    missing = [c for c in [COL_ID, COL_DATE] if c not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_personnel_orders.py 상단의 컬럼명 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'researcher_id': df['researcher_id'],
        'order_date':    df[COL_DATE].apply(_parse_date),
        'order_name':    _col(COL_NAME),
        'order_dep':     _col(COL_DEP),
        'order_cl':      df[COL_CL].apply(_strip_paren) if COL_CL in df.columns
                         else pd.Series('', index=df.index),
    })

    result = result.sort_values(['researcher_id', 'order_date']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'hr_orders.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique()
    print(f'[OK]   hr_orders.csv 저장 ({len(result)}행, {n}명)')
    return True


if __name__ == '__main__':
    process()
