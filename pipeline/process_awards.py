"""
시상 이력 처리 모듈

원천 파일: data/raw/시상 세부사항.xlsx
출력 파일: data/processed/awards.csv

읽는 컬럼:
  사번, 수상일, 수상 유형, 수상명, 수여기관, 설명

컬럼명 설정은 파일 상단의 COL_* 상수에서 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

AWARDS_FILE = '시상 세부사항.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID          = '사번'
COL_DATE        = '수상일'
COL_TYPE        = '수상 유형'
COL_NAME        = '수상명'
COL_ORG         = '수여기관'
COL_DESC        = '설명'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def _fmt_date(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    s = str(val).strip()
    if s in ('', 'nan', 'None', 'NaT'):
        return ''
    try:
        return pd.to_datetime(s).strftime('%Y-%m-%d')
    except Exception:
        return s


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, AWARDS_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {AWARDS_FILE} 파일 없음 — awards_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_awards.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'researcher_id': df['researcher_id'],
        'award_date':    df[COL_DATE].apply(_fmt_date) if COL_DATE in df.columns
                         else pd.Series('', index=df.index),
        'award_type':    _col(COL_TYPE),
        'award_name':    _col(COL_NAME),
        'awarding_org':  _col(COL_ORG),
        'description':   _col(COL_DESC),
    })

    result['year'] = result['award_date'].str[:4].replace('', pd.NA)
    result = result.sort_values(['researcher_id', 'award_date'], ascending=[True, False]).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'awards.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n = result['researcher_id'].nunique()
    print(f'[OK]   awards.csv 저장 ({len(result)}행, {n}명)')
    return True


if __name__ == '__main__':
    process()
