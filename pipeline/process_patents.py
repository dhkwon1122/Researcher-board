"""
특허 리스트 처리 모듈

원천 파일: data/raw/특허 리스트.xlsx
출력 파일: data/processed/patents.csv

처리 로직:
  - 동일 접수ID → 동일 특허 (발명자별 1행 유지)
  - 사번으로 발명자(연구원) 구분, 8자리 텍스트로 정규화

컬럼 설정 (실제 파일 헤더에 맞게 상단 상수 수정):
  COL_ID      : 사번 컬럼명
  COL_APP_ID  : 접수ID 컬럼명
  COL_TITLE   : 발명명칭 - 영문 컬럼명
  COL_TITLE_KO: 발명명칭(한글) 컬럼명
  COL_STATUS  : 진행상태 컬럼명
  COL_SHARE   : 지분율 컬럼명
  COL_LEAD    : 대표발명자여부 컬럼명
  COL_GRADE   : 현재등급 컬럼명
  COL_GRADE_A : 현재등급 - A급구분 컬럼명
"""

import csv
import os
import sys

import pandas as pd

RAW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'processed')

PATENT_FILE = '특허 리스트.xlsx'

# ── 컬럼명 설정 (파일 헤더와 다를 경우 여기서 수정) ──────────────────────────
COL_ID       = '사번'
COL_APP_ID   = '접수ID'
COL_TITLE    = '발명명칭 - 영문'
COL_TITLE_KO = '발명명칭'
COL_STATUS   = '진행상태'
COL_SHARE    = '지분율'
COL_LEAD     = '대표발명자여부'
COL_GRADE    = '현재등급'
COL_GRADE_A  = '현재등급 - A급구분'

# 있으면 추가로 가져오는 선택 컬럼 (원본명 → CSV 컬럼명)
OPTIONAL_COLS = [
    ('출원번호', 'application_no'),
    ('출원일',   'application_date'),
    ('등록번호', 'registration_no'),
    ('등록일',   'registration_date'),
    ('국가',     'country'),
    ('국가명',   'country'),   # '국가' 없으면 '국가명' 시도
]
# ─────────────────────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from excel_reader import read_xlsx, norm_id


def process() -> bool:
    raw_path = os.path.join(RAW_DIR, PATENT_FILE)
    if not os.path.exists(raw_path):
        print(f'[SKIP] {PATENT_FILE} 파일 없음 — patents_raw 폴백 시도')
        return False

    df = read_xlsx(raw_path)

    missing = [c for c in [COL_ID, COL_APP_ID] if c not in df.columns]
    if missing:
        print(
            f'[ERROR] 필수 컬럼 없음: {missing}\n'
            f'  process_patents.py 상단의 컬럼명 상수를 실제 헤더에 맞게 수정하세요.\n'
            f'  현재 파일 헤더: {list(df.columns)}'
        )
        return False

    # 사번 정규화
    df['researcher_id'] = df[COL_ID].apply(norm_id)
    df = df[df['researcher_id'] != ''].copy()

    # ── 핵심 컬럼 매핑 ─────────────────────────────────────────────────────────
    def _col(name):
        return df[name].astype(str).str.strip() if name in df.columns else pd.Series('', index=df.index)

    result = pd.DataFrame({
        'researcher_id':      df['researcher_id'],
        'application_id':     _col(COL_APP_ID),
        'title':              _col(COL_TITLE),
        'title_ko':           _col(COL_TITLE_KO),
        'status':             _col(COL_STATUS),
        'share_ratio':        _col(COL_SHARE),
        'is_lead_inventor':   _col(COL_LEAD),
        'patent_grade':       _col(COL_GRADE),
        'patent_grade_a_sub': _col(COL_GRADE_A),
    })

    # ── 선택 컬럼 (출원번호·출원일·등록번호·등록일·국가) ──────────────────────
    filled = set()
    for src_col, dst_col in OPTIONAL_COLS:
        if dst_col in filled:
            continue
        if src_col in df.columns:
            result[dst_col] = df[src_col].astype(str).str.strip()
            filled.add(dst_col)
    for dst_col in ['application_no', 'application_date', 'registration_no',
                    'registration_date', 'country']:
        if dst_col not in result.columns:
            result[dst_col] = ''

    result = result.sort_values(['researcher_id', 'application_id']).reset_index(drop=True)

    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, 'patents.csv')
    result.to_csv(out_path, index=False, encoding='utf-8-sig', quoting=csv.QUOTE_NONNUMERIC)

    n_patents   = result['application_id'].nunique()
    n_inventors = result['researcher_id'].nunique()
    print(f'[OK]   patents.csv 저장 ({len(result)}행 / 특허 {n_patents}건 / 발명자 {n_inventors}명)')
    return True


if __name__ == '__main__':
    process()
