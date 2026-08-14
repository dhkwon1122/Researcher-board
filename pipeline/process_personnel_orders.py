"""
인사발령 이력 처리 모듈

원천: source_reader.read_source('hr_orders')
  → DB hr_orders_stg 테이블 또는 data/raw_csv/hr_orders.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/인사발령이력.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/hr_orders.csv

컬럼 매핑:
  사원번호 → researcher_id (8자리 제로패딩)
  발령일자(YYYYMMDD) → order_date (YYYY-MM-DD)
  발령명   → order_name
  부서     → order_dep
  직급명   → order_cl (괄호와 괄호 안 내용 제거, 예: '선임연구원(과장)' → '선임연구원')
  직책명   → order_assignment

컬럼 설정 (실제 파일 헤더에 맞게 상단 상수 수정):
  COL_ID         : 사원번호 컬럼명
  COL_DATE       : 발령일자 컬럼명
  COL_NAME       : 발령명 컬럼명
  COL_DEP        : 부서 컬럼명
  COL_CL         : 직급명 컬럼명
  COL_ASSIGNMENT : 직책명 컬럼명
"""

import os
import re
import sys

import pandas as pd

ORDERS_FILE = '인사발령이력.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID         = '사원번호'
COL_DATE       = '발령일자'
COL_NAME       = '발령명'
COL_DEP        = '부서'
COL_CL         = '직급명'
COL_ASSIGNMENT = '직책명'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import parse_yyyymmdd, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source

_PAREN_RE = re.compile(r'[\(（][^)）]*[\)）]')


def _strip_paren(val) -> str:
    """괄호와 괄호 안 내용 제거 (예: '선임연구원(과장)' → '선임연구원')."""
    s = str(val).strip()
    return _PAREN_RE.sub('', s).strip()


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('hr_orders')
        if df is None:
            print('[SKIP] hr_orders 원천 데이터 없음 '
                  '(DB hr_orders_stg 또는 data/raw_csv/hr_orders.csv) — hr_orders_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, ORDERS_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path, header_row=0)
        else:
            df = None
            print(f'[SKIP] {ORDERS_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False
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
        'researcher_id':    df['researcher_id'],
        'order_date':       df[COL_DATE].apply(parse_yyyymmdd),
        'order_name':       _col(COL_NAME),
        'order_dep':        _col(COL_DEP),
        'order_cl':         df[COL_CL].apply(_strip_paren) if COL_CL in df.columns
                            else pd.Series('', index=df.index),
        'order_assignment': _col(COL_ASSIGNMENT),
    })

    result = result.sort_values(['researcher_id', 'order_date']).reset_index(drop=True)

    out_path = os.path.join(OUT_DIR, 'hr_orders.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['hr_orders'])

    n = merged['researcher_id'].nunique()
    print(f'[OK]   hr_orders.csv 저장 (총 {len(merged)}행, {n}명, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
