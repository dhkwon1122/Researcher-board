"""
시상 이력 처리 모듈

원천: source_reader.read_source('awards')
  → DB awards_stg 테이블 또는 data/raw_csv/awards.csv
  (1단계 xlsx_to_raw_csv.py가 data/raw/시상 세부사항.xlsx를 DRM 제거해 만든 사본)
출력 파일: data/processed/awards.csv

읽는 컬럼:
  사번, 수상일, 수상 유형, 수상명, 수여기관, 설명

컬럼명 설정은 파일 상단의 COL_* 상수에서 수정하세요.
"""

import os
import sys

import pandas as pd

AWARDS_FILE = '시상 세부사항.xlsx'
_AWARDS_HEADER_ROW = 0  # sources.py 매니페스트 기준 (1번째 행)

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID          = '사번'
COL_DATE        = '수상일'
COL_TYPE        = '수상 유형'
COL_NAME        = '수상명'
COL_ORG         = '수여기관'
COL_DESC        = '설명'
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import RAW_DIR, OUT_DIR  # noqa: E402
from excel_reader import parse_flexible_date as _fmt_date, read_xlsx, norm_id
from merge_utils import TABLE_KEYS, write_merged
from source_reader import read_source


def process(raw_dir: str = RAW_DIR) -> bool:
    if raw_dir == RAW_DIR:
        df = read_source('awards')
        if df is None:
            print('[SKIP] awards 원천 데이터 없음 '
                  '(DB awards_stg 또는 data/raw_csv/awards.csv) — awards_raw 폴백 시도')
    else:
        raw_path = os.path.join(raw_dir, AWARDS_FILE)
        if os.path.exists(raw_path):
            df = read_xlsx(raw_path, header_row=_AWARDS_HEADER_ROW)
        else:
            df = None
            print(f'[SKIP] {AWARDS_FILE} 파일 없음({raw_dir})')

    if df is None:
        return False
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

    out_path = os.path.join(OUT_DIR, 'awards.csv')
    merged = write_merged(out_path, result, TABLE_KEYS['awards'])

    n = merged['researcher_id'].nunique()
    print(f'[OK]   awards.csv 저장 (총 {len(merged)}행, {n}명, 이번 파일 {len(result)}행 반영)')
    return True


if __name__ == '__main__':
    process()
