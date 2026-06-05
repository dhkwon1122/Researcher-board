"""
양성 인력 현황 처리 모듈

원천 파일: data/raw/양성_인력_현황.xlsx
출력 파일: data/processed/nurturing.csv

읽는 컬럼:
  사번, 양성구분, 세부양성구분, 연수시작일, 연수종료일,
  국가, 도시, 교육기관, 전공학과, 의무근무 종료일

컬럼명 설정은 파일 상단의 COL_* 상수에서 수정하세요.
"""

import csv
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

NURTURING_FILE = '양성_인력_현황.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID          = '사번'
COL_CATEGORY    = '양성구분'
COL_SUBCATEGORY = '세부양성구분'
COL_START       = '연수시작일'
COL_END         = '연수종료일'
COL_COUNTRY     = '국가'
COL_CITY        = '도시'
COL_INSTITUTION = '교육기관'
COL_MAJOR       = '전공학과'
COL_SERVICE_END = '의무근무 종료일'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def _fmt_date(val) -> str:
    """날짜 값을 YYYY-MM-DD 문자열로 변환."""
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
    raw_path = os.path.join(RAW_DIR, NURTURING_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {NURTURING_FILE} 파일 없음 — nurturing_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)
    df.columns = [str(c).strip() for c in df.columns]

    if COL_ID not in df.columns:
        print(
            f'[ERROR] 필수 컬럼 없음: [{COL_ID}]\n'
            f'  process_nurturing.py 상단의 COL_ID를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    # 사번 정규화
    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'researcher_id': df['researcher_id'],
        'category':      _col(COL_CATEGORY),
        'subcategory':   _col(COL_SUBCATEGORY),
        'start_date':    df[COL_START].apply(_fmt_date) if COL_START in df.columns
                         else pd.Series('', index=df.index),
        'end_date':      df[COL_END].apply(_fmt_date) if COL_END in df.columns
                         else pd.Series('', index=df.index),
        'country':       _col(COL_COUNTRY),
        'city':          _col(COL_CITY),
        'institution':   _col(COL_INSTITUTION),
        'major':         _col(COL_MAJOR),
        'service_end_date': df[COL_SERVICE_END].apply(_fmt_date) if COL_SERVICE_END in df.columns
                            else pd.Series('', index=df.index),
    })

    # 연수시작일 기준 연도 파생 (표시용)
    result['year'] = result['start_date'].str[:4].replace('', pd.NA)

    result = result.sort_values(['researcher_id', 'start_date']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'nurturing.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n_researchers = result['researcher_id'].nunique()
    print(f'[OK]   nurturing.csv 저장 ({len(result)}행, {n_researchers}명)')
    return True


if __name__ == '__main__':
    process()
